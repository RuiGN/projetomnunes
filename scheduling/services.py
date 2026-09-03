"""Transactional services for availability and the appointment lifecycle."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import linked_patients_for_therapist, patient_profile_for_user

from .events import (
    appointment_canceled,
    appointment_completed,
    appointment_confirmed,
    appointment_no_show,
    appointment_requested,
    appointment_reschedule_requested,
)
from .models import (
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
    AvailabilityOverride,
    AvailabilityPattern,
    ScheduleBlock,
    Unit,
)
from .models import (
    Service as ServiceModel,
)

__all__ = [
    "Service",
    "ACTIVE_OCCUPYING_STATUSES",
    "cancel_appointment",
    "complete_appointment",
    "confirm_appointment",
    "free_slots",
    "record_no_show",
    "request_appointment",
    "request_reschedule",
]

# Statuses whose slot is still occupied (blocks concurrent bookings).
ACTIVE_OCCUPYING_STATUSES = frozenset(
    {
        AppointmentStatus.REQUESTED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.RESCHEDULE_REQUESTED,
    }
)

# Allowed transitions for the explicit appointment state machine.
TRANSITIONS: dict[str, frozenset[str]] = {
    AppointmentStatus.REQUESTED: frozenset(
        {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELED,
            AppointmentStatus.RESCHEDULE_REQUESTED,
        }
    ),
    AppointmentStatus.CONFIRMED: frozenset(
        {
            AppointmentStatus.RESCHEDULE_REQUESTED,
            AppointmentStatus.CANCELED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        }
    ),
    AppointmentStatus.RESCHEDULE_REQUESTED: frozenset(
        {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELED,
            AppointmentStatus.REQUESTED,
        }
    ),
    AppointmentStatus.CANCELED: frozenset(),
    AppointmentStatus.COMPLETED: frozenset(),
    AppointmentStatus.NO_SHOW: frozenset(),
}


def _unit_timezone(unit: Unit) -> ZoneInfo:
    """Resolve the unit's timezone, falling back to the platform default."""
    try:
        return ZoneInfo(unit.timezone_name or "America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Sao_Paulo")


def _as_utc(value: datetime) -> datetime:
    """Normalize one aware datetime to UTC for interval comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Return whether two half-open [start, end) intervals overlap."""
    return _as_utc(a_start) < _as_utc(b_end) and _as_utc(b_start) < _as_utc(a_end)


def _day_windows(
    *, unit: Unit, professional_id: UUID, day: date, tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """Return raw availability windows for one professional on one local date."""
    override = AvailabilityOverride.infrastructure_objects.filter(
        clinic_id=unit.clinic_id,
        professional_id=professional_id,
        unit_id=unit.pk,
        date=day,
    ).first()
    if override is not None:
        if not override.available:
            return []
        if override.start_time is None or override.end_time is None:
            return []
        start = datetime.combine(day, override.start_time, tzinfo=tz)
        end = datetime.combine(day, override.end_time, tzinfo=tz)
        return [(start, end)]

    patterns = AvailabilityPattern.infrastructure_objects.filter(
        clinic_id=unit.clinic_id,
        professional_id=professional_id,
        unit_id=unit.pk,
        weekday=day.weekday(),
        is_active=True,
        valid_from__lte=day,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=day))
    windows: list[tuple[datetime, datetime]] = []
    for pattern in patterns:
        start = datetime.combine(day, pattern.start_time, tzinfo=tz)
        end = datetime.combine(day, pattern.end_time, tzinfo=tz)
        windows.append((start, end))
    return windows


def _occupied_intervals(
    *, clinic_id: UUID, professional_id: UUID, from_utc: datetime, to_utc: datetime
) -> list[tuple[datetime, datetime]]:
    """Collect blocking windows and occupying appointments in UTC-normalized form."""
    intervals: list[tuple[datetime, datetime]] = []
    blocks = ScheduleBlock.infrastructure_objects.filter(
        clinic_id=clinic_id,
        professional_id=professional_id,
        is_active=True,
        start_at__lt=to_utc,
        end_at__gt=from_utc,
    )
    for block in blocks:
        intervals.append((block.start_at, block.end_at))
    appointments = Appointment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        professional_id=professional_id,
        status__in=ACTIVE_OCCUPYING_STATUSES,
        start_at__lt=to_utc,
        end_at__gt=from_utc,
    )
    for appointment in appointments:
        intervals.append((appointment.start_at, appointment.end_at))
    intervals.sort(key=lambda item: _as_utc(item[0]))
    return intervals


def _generate_slots(
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    buffer: timedelta,
    occupied: list[tuple[datetime, datetime]],
) -> list[datetime]:
    """Yield non-overlapping slot starts on a fixed grid, in UTC arithmetic.

    Arithmetic runs in UTC so daylight-saving transitions shift the wall clock
    by exactly the skipped/repeated hour instead of producing nonexistent times.
    """
    step = duration + buffer
    end_utc = _as_utc(window_end)
    cursor = _as_utc(window_start)
    slots: list[datetime] = []
    while cursor + duration <= end_utc:
        candidate_end = cursor + duration
        if not any(
            _overlaps(cursor, candidate_end, start, end) for start, end in occupied
        ):
            slots.append(cursor.astimezone(window_start.tzinfo))
        cursor += step
    return slots


def free_slots(
    *,
    clinic_id: UUID,
    professional_id: UUID,
    unit_id: UUID,
    service_id: UUID,
    from_date: date,
    to_date: date,
) -> list[datetime]:
    """Return available slot starts for one professional, unit and service.

    Slots are returned as aware datetimes in the unit's own timezone.
    """
    if to_date < from_date:
        raise ValidationError("O período final deve ser igual ou posterior ao inicial.")
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    service = ServiceModel.infrastructure_objects.filter(
        pk=service_id, clinic_id=clinic_id
    ).first()
    if service is None:
        raise ValidationError("Serviço não encontrado.")

    tz = _unit_timezone(unit)
    duration = timedelta(minutes=service.duration_minutes)
    buffer = timedelta(minutes=service.buffer_minutes)

    slots: list[datetime] = []
    day = from_date
    while day <= to_date:
        for window_start, window_end in _day_windows(
            unit=unit, professional_id=professional_id, day=day, tz=tz
        ):
            from_utc = _as_utc(window_start)
            to_utc = _as_utc(window_end)
            occupied = _occupied_intervals(
                clinic_id=clinic_id,
                professional_id=professional_id,
                from_utc=from_utc,
                to_utc=to_utc,
            )
            slots.extend(
                _generate_slots(
                    window_start=window_start,
                    window_end=window_end,
                    duration=duration,
                    buffer=buffer,
                    occupied=occupied,
                )
            )
        day += timedelta(days=1)
    return slots


def _record_event(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    kind: str,
    actor_id: UUID,
    reason: str = "",
    detail: dict[str, object] | None = None,
) -> None:
    AppointmentEvent.infrastructure_objects.create(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        kind=kind,
        actor_id=actor_id,
        reason=reason,
        detail=detail or {},
    )


def _ensure_valid_transition(current: str, target: str) -> None:
    allowed = TRANSITIONS.get(current)
    if allowed is None or target not in allowed:
        raise ValidationError(f"Transição inválida de {current} para {target}.")


def _assert_no_overlap(
    *,
    clinic_id: UUID,
    professional_id: UUID,
    start_at: datetime,
    end_at: datetime,
    exclude_id: UUID | None = None,
) -> None:
    existing = Appointment.infrastructure_objects.select_for_update().filter(
        clinic_id=clinic_id,
        professional_id=professional_id,
        status__in=ACTIVE_OCCUPYING_STATUSES,
        start_at__lt=end_at,
        end_at__gt=start_at,
    )
    if exclude_id is not None:
        existing = existing.exclude(pk=exclude_id)
    if existing.exists():
        raise ValidationError(
            "Já existe uma consulta neste horário para o profissional."
        )


def _validate_window(start_at: datetime, end_at: datetime) -> None:
    if end_at <= start_at:
        raise ValidationError("O horário final deve ser posterior ao inicial.")


def _own_patient_profile_id(*, clinic_id: UUID, actor: AbstractBaseUser) -> UUID:
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied
    return profile.pk


def _therapist_or_staff_can_manage(
    *, clinic_id: UUID, actor: AbstractBaseUser, patient_profile_id: UUID
) -> bool:
    """True when the actor is clinic admin/staff or the linked therapist."""
    today = timezone.localdate()
    for role in ("clinic_admin", "administrative_staff"):
        if has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        ):
            return True
    if has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=today
    ):
        linked = linked_patients_for_therapist(
            clinic_id=clinic_id, therapist_id=actor.pk, on_date=today
        )
        return any(row.patient_profile_id == patient_profile_id for row in linked)
    return False


def _require_staff_or_linked(
    *, clinic_id: UUID, actor: AbstractBaseUser, patient_profile_id: UUID
) -> None:
    if not _therapist_or_staff_can_manage(
        clinic_id=clinic_id, actor=actor, patient_profile_id=patient_profile_id
    ):
        raise PermissionDenied


@transaction.atomic
def request_appointment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    service_id: UUID,
    professional_id: UUID,
    unit_id: UUID,
    start_at: datetime,
    end_at: datetime,
    idempotency_key: str,
    request_id: UUID,
) -> Appointment:
    """Create a patient-requested appointment idempotently (8.8.2.2)."""
    _validate_window(start_at, end_at)
    patient_profile_id = _own_patient_profile_id(clinic_id=clinic_id, actor=actor)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = Appointment.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing

    service = ServiceModel.infrastructure_objects.filter(
        pk=service_id, clinic_id=clinic_id, is_active=True
    ).first()
    if service is None:
        raise ValidationError("Serviço não encontrado ou inativo.")

    _assert_no_overlap(
        clinic_id=clinic_id,
        professional_id=professional_id,
        start_at=start_at,
        end_at=end_at,
    )

    appointment = Appointment(
        clinic_id=clinic_id,
        service_id=service_id,
        professional_id=professional_id,
        patient_profile_id=patient_profile_id,
        unit_id=unit_id,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.REQUESTED,
        idempotency_key=key,
        requested_by_id=actor.pk,
    )
    appointment.full_clean(validate_unique=False, validate_constraints=False)
    appointment.save(force_insert=True)
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.REQUESTED,
        actor_id=actor.pk,
    )
    appointment_requested.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment


@transaction.atomic
def confirm_appointment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    request_id: UUID,
) -> Appointment:
    """Confirm a requested or rescheduled appointment, reserving the slot atomically."""
    appointment = (
        Appointment.infrastructure_objects.select_for_update()
        .filter(pk=appointment_id, clinic_id=clinic_id)
        .first()
    )
    if appointment is None:
        raise PermissionDenied
    _require_staff_or_linked(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=appointment.patient_profile_id,
    )
    _ensure_valid_transition(appointment.status, AppointmentStatus.CONFIRMED)
    _assert_no_overlap(
        clinic_id=clinic_id,
        professional_id=appointment.professional_id,
        start_at=appointment.start_at,
        end_at=appointment.end_at,
        exclude_id=appointment.pk,
    )
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.save(update_fields=("status", "updated_at"))
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.CONFIRMED,
        actor_id=actor.pk,
    )
    appointment_confirmed.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment


@transaction.atomic
def request_reschedule(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    start_at: datetime,
    end_at: datetime,
    request_id: UUID,
) -> Appointment:
    """Propose a new slot, releasing the old one only after re-validation."""
    _validate_window(start_at, end_at)
    appointment = (
        Appointment.infrastructure_objects.select_for_update()
        .filter(pk=appointment_id, clinic_id=clinic_id)
        .first()
    )
    if appointment is None:
        raise PermissionDenied
    _require_staff_or_linked(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=appointment.patient_profile_id,
    )
    _ensure_valid_transition(appointment.status, AppointmentStatus.RESCHEDULE_REQUESTED)
    _assert_no_overlap(
        clinic_id=clinic_id,
        professional_id=appointment.professional_id,
        start_at=start_at,
        end_at=end_at,
        exclude_id=appointment.pk,
    )
    detail: dict[str, object] = {
        "from_start": appointment.start_at.isoformat(),
        "from_end": appointment.end_at.isoformat(),
        "to_start": start_at.isoformat(),
        "to_end": end_at.isoformat(),
    }
    appointment.start_at = start_at
    appointment.end_at = end_at
    appointment.status = AppointmentStatus.RESCHEDULE_REQUESTED
    appointment.save(update_fields=("start_at", "end_at", "status", "updated_at"))
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.RESCHEDULE_REQUESTED,
        actor_id=actor.pk,
        detail=detail,
    )
    appointment_reschedule_requested.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment


@transaction.atomic
def cancel_appointment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    reason: str = "",
    request_id: UUID,
) -> Appointment:
    """Cancel one appointment, releasing its slot and preserving history."""
    appointment = (
        Appointment.infrastructure_objects.select_for_update()
        .filter(pk=appointment_id, clinic_id=clinic_id)
        .first()
    )
    if appointment is None:
        raise PermissionDenied
    is_patient = (
        has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=actor.pk,
            role="patient",
            on_date=timezone.localdate(),
        )
        and appointment.requested_by_id == actor.pk
    )
    if not is_patient and not _therapist_or_staff_can_manage(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=appointment.patient_profile_id,
    ):
        raise PermissionDenied
    _ensure_valid_transition(appointment.status, AppointmentStatus.CANCELED)
    appointment.status = AppointmentStatus.CANCELED
    appointment.cancel_reason = reason.strip()
    appointment.save(update_fields=("status", "cancel_reason", "updated_at"))
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.CANCELED,
        actor_id=actor.pk,
        reason=reason.strip(),
    )
    appointment_canceled.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment


def _record_attendance(
    *, clinic_id: UUID, actor: AbstractBaseUser, appointment_id: UUID, target: str
) -> Appointment:
    appointment = (
        Appointment.infrastructure_objects.select_for_update()
        .filter(pk=appointment_id, clinic_id=clinic_id)
        .first()
    )
    if appointment is None:
        raise PermissionDenied
    _require_staff_or_linked(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=appointment.patient_profile_id,
    )
    _ensure_valid_transition(appointment.status, target)
    appointment.status = target
    appointment.attendance_recorded_by_id = actor.pk
    appointment.save(update_fields=("status", "attendance_recorded_by", "updated_at"))
    return appointment


@transaction.atomic
def complete_appointment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    request_id: UUID,
) -> Appointment:
    """Mark one confirmed appointment as completed by an authorized profile."""
    appointment = _record_attendance(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        target=AppointmentStatus.COMPLETED,
    )
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.COMPLETED,
        actor_id=actor.pk,
    )
    appointment_completed.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment


@transaction.atomic
def record_no_show(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    request_id: UUID,
) -> Appointment:
    """Record an authorized no-show for one confirmed appointment."""
    appointment = _record_attendance(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        target=AppointmentStatus.NO_SHOW,
    )
    _record_event(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        kind=AppointmentEvent.Kind.NO_SHOW,
        actor_id=actor.pk,
    )
    appointment_no_show.send(
        sender=Appointment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(appointment.pk),
        request_id=request_id,
    )
    return appointment
