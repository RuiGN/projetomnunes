"""Reminder preferences, idempotent scheduling and delivery records."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.services import Service as Service
from goals.selectors import patient_profile_low_energy_active
from people.selectors import patient_profile_for_user

from .events import reminder_canceled, reminder_scheduled
from .models import (
    Appointment,
    NotificationEvent,
    NotificationStatus,
    Reminder,
    ReminderChannel,
    ReminderPreference,
    ReminderStatus,
    ReminderType,
)
from .services import _own_patient_profile_id, _therapist_or_staff_can_manage

__all__ = [
    "Service",
    "ESSENTIAL_REMINDER_TYPES",
    "cancel_reminders_for_appointment",
    "mark_reminder_delivered",
    "mark_reminder_failed",
    "record_notification_event",
    "schedule_appointment_reminder",
    "schedule_reminder",
    "snooze_reminder",
    "upsert_reminder_preference",
]

MAX_DAILY_LIMIT = 24

# Reminder types explicitly essential and never suppressed by low-energy mode.
ESSENTIAL_REMINDER_TYPES = frozenset({ReminderType.APPOINTMENT})


@transaction.atomic
def upsert_reminder_preference(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    reminder_type: str,
    channel: str,
    enabled: bool,
    advance_minutes: int,
    silence_start: time | None,
    silence_end: time | None,
    timezone_name: str,
    max_daily: int,
) -> ReminderPreference:
    """Create or update one patient's own reminder preference (8.8.3.1)."""
    profile_id = _own_patient_profile_id(clinic_id=clinic_id, actor=actor)
    if reminder_type not in ReminderType.values:
        raise ValidationError("Tipo de lembrete inválido.")
    if channel not in ReminderChannel.values:
        raise ValidationError("Canal de lembrete inválido.")
    if advance_minutes < 0:
        raise ValidationError("A antecedência não pode ser negativa.")
    if max_daily < 1 or max_daily > MAX_DAILY_LIMIT:
        raise ValidationError(
            f"A frequência máxima diária deve ficar entre 1 e {MAX_DAILY_LIMIT}."
        )
    if silence_start is not None and silence_end is None:
        raise ValidationError("Informe o fim do horário de silêncio.")
    if silence_end is not None and silence_start is None:
        raise ValidationError("Informe o início do horário de silêncio.")

    preference, _created = ReminderPreference.infrastructure_objects.update_or_create(
        clinic_id=clinic_id,
        patient_profile_id=profile_id,
        reminder_type=reminder_type,
        channel=channel,
        defaults={
            "enabled": enabled,
            "advance_minutes": advance_minutes,
            "silence_start": silence_start,
            "silence_end": silence_end,
            "timezone_name": timezone_name.strip() or "America/Sao_Paulo",
            "max_daily": max_daily,
        },
    )
    return preference


@transaction.atomic
def schedule_appointment_reminder(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    idempotency_key: str,
    request_id: UUID,
) -> Reminder | None:
    """Schedule one appointment reminder when the patient's preference allows it."""
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = Reminder.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing

    appointment = Appointment.infrastructure_objects.filter(
        pk=appointment_id, clinic_id=clinic_id
    ).first()
    if appointment is None:
        raise PermissionDenied
    if not _therapist_or_staff_can_manage(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=appointment.patient_profile_id,
    ):
        raise PermissionDenied

    preference = (
        ReminderPreference.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=appointment.patient_profile_id,
            reminder_type=ReminderType.APPOINTMENT,
            enabled=True,
        )
        .first()
    )
    if preference is None:
        return None

    scheduled_for = appointment.start_at - timedelta(minutes=preference.advance_minutes)
    reminder = Reminder.infrastructure_objects.create(
        clinic_id=clinic_id,
        patient_profile_id=appointment.patient_profile_id,
        reminder_type=ReminderType.APPOINTMENT,
        channel=preference.channel,
        appointment_id=appointment.pk,
        scheduled_for=scheduled_for,
        status=ReminderStatus.PENDING,
        idempotency_key=key,
    )
    reminder_scheduled.send(
        sender=Reminder,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(reminder.pk),
        request_id=request_id,
    )
    return reminder


@transaction.atomic
def cancel_reminders_for_appointment(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    request_id: UUID,
) -> int:
    """Cancel pending reminders when an appointment changes state (8.8.3.2)."""
    cancelled = 0
    reminders = Reminder.infrastructure_objects.select_for_update().filter(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        status=ReminderStatus.PENDING,
    )
    for reminder in reminders:
        reminder.status = ReminderStatus.CANCELED
        reminder.save(update_fields=("status", "updated_at"))
        reminder_canceled.send(
            sender=Reminder,
            clinic_id=clinic_id,
            actor_id=None,
            resource_id=str(reminder.pk),
            request_id=request_id,
        )
        cancelled += 1
    return cancelled


def mark_reminder_delivered(
    *, clinic_id: UUID, reminder_id: UUID, delivery_reference: str
) -> Reminder:
    """Mark one pending reminder as delivered without storing sensitive content."""
    reminder = Reminder.infrastructure_objects.filter(
        pk=reminder_id, clinic_id=clinic_id
    ).first()
    if reminder is None:
        raise PermissionDenied
    reminder.status = ReminderStatus.SENT
    reminder.sent_at = timezone.now()
    reminder.delivery_reference = delivery_reference.strip()
    reminder.save(
        update_fields=("status", "sent_at", "delivery_reference", "updated_at")
    )
    return reminder


def mark_reminder_failed(*, clinic_id: UUID, reminder_id: UUID) -> Reminder:
    """Mark one pending reminder as failed for retry/alert purposes."""
    reminder = Reminder.infrastructure_objects.filter(
        pk=reminder_id, clinic_id=clinic_id
    ).first()
    if reminder is None:
        raise PermissionDenied
    reminder.status = ReminderStatus.FAILED
    reminder.save(update_fields=("status", "updated_at"))
    return reminder


def record_notification_event(
    *,
    clinic_id: UUID,
    recipient_id: UUID,
    kind: str,
    channel: str,
    status: str = NotificationStatus.QUEUED,
    correlation_id: str = "",
) -> NotificationEvent:
    """Append one minimized delivery record with no sensitive payload."""
    if kind not in NotificationEvent.Kind.values:
        raise ValidationError("Tipo de notificação inválido.")
    if channel not in ReminderChannel.values:
        raise ValidationError("Canal de notificação inválido.")
    if status not in NotificationStatus.values:
        raise ValidationError("Estado de notificação inválido.")
    return NotificationEvent.infrastructure_objects.create(
        clinic_id=clinic_id,
        recipient_id=recipient_id,
        kind=kind,
        channel=channel,
        status=status,
        correlation_id=correlation_id.strip(),
    )


@transaction.atomic
def schedule_reminder(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    reminder_type: str,
    channel: str,
    scheduled_for: datetime,
    idempotency_key: str,
    request_id: UUID,
    appointment_id: UUID | None = None,
    is_essential: bool = False,
) -> Reminder | None:
    """Schedule one reminder idempotently, suppressing non-essential types
    while a low-energy mode is active (8.8.3.2 + 8.8.3.4)."""
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    if reminder_type not in ReminderType.values:
        raise ValidationError("Tipo de lembrete inválido.")
    if channel not in ReminderChannel.values:
        raise ValidationError("Canal de lembrete inválido.")

    existing = Reminder.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing

    own_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if own_profile is not None and own_profile.pk == patient_profile_id:
        pass  # patient schedules their own reminder
    elif not _therapist_or_staff_can_manage(
        clinic_id=clinic_id, actor=actor, patient_profile_id=patient_profile_id
    ):
        raise PermissionDenied

    if (
        not is_essential
        and reminder_type not in ESSENTIAL_REMINDER_TYPES
        and patient_profile_low_energy_active(
            clinic_id=clinic_id, patient_profile_id=patient_profile_id
        )
    ):
        return None

    reminder = Reminder.infrastructure_objects.create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        reminder_type=reminder_type,
        channel=channel,
        appointment_id=appointment_id,
        scheduled_for=scheduled_for,
        status=ReminderStatus.PENDING,
        idempotency_key=key,
    )
    reminder_scheduled.send(
        sender=Reminder,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(reminder.pk),
        request_id=request_id,
    )
    return reminder


@transaction.atomic
def snooze_reminder(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    reminder_id: UUID,
    minutes: int,
    request_id: UUID,
) -> Reminder:
    """Delay one pending reminder by the patient who owns it (8.8.3.4)."""
    if minutes <= 0:
        raise ValidationError("O adiamento deve ser positivo.")
    profile_id = _own_patient_profile_id(clinic_id=clinic_id, actor=actor)
    reminder = (
        Reminder.infrastructure_objects.select_for_update()
        .filter(pk=reminder_id, clinic_id=clinic_id, patient_profile_id=profile_id)
        .first()
    )
    if reminder is None:
        raise PermissionDenied
    if reminder.status != ReminderStatus.PENDING:
        raise ValidationError("Somente lembretes pendentes podem ser adiados.")
    reminder.scheduled_for = reminder.scheduled_for + timedelta(minutes=minutes)
    reminder.save(update_fields=("scheduled_for", "updated_at"))
    return reminder
