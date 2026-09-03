"""Transactional services for the reception waitlist."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.services import lock_clinic_for_update
from core.services import Service as Service

from .models import (
    Appointment,
    AppointmentStatus,
    Unit,
    WaitlistEntry,
    WaitlistStatus,
)
from .models import (
    Service as ServiceModel,
)

__all__ = [
    "Service",
    "add_waitlist_entry",
    "cancel_waitlist_entry",
    "fill_waitlist_entry",
]


def _require_reception_role(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    from django.utils import timezone

    today = timezone.localdate()
    if not any(
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        )
        for role in ("clinic_admin", "administrative_staff")
    ):
        raise PermissionDenied


@transaction.atomic
def add_waitlist_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    unit_id: UUID,
    service_id: UUID,
    preferred_period: str,
    contact_note: str,
    request_id: UUID,
) -> WaitlistEntry:
    """Record one reception waitlist request with period and unit preference."""
    _require_reception_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    service = ServiceModel.infrastructure_objects.filter(
        pk=service_id, clinic_id=clinic_id, is_active=True
    ).first()
    if service is None:
        raise ValidationError("Serviço não encontrado ou inativo.")
    entry = WaitlistEntry.infrastructure_objects.create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period=preferred_period.strip(),
        contact_note=contact_note.strip(),
        status=WaitlistStatus.WAITING,
        requested_by_id=actor.pk,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="waitlist_entry",
        resource_id=str(entry.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return entry


@transaction.atomic
def cancel_waitlist_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    entry_id: UUID,
    request_id: UUID,
) -> WaitlistEntry:
    """Cancel one waitlist entry that is still waiting."""
    _require_reception_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    entry = (
        WaitlistEntry.infrastructure_objects.select_for_update()
        .filter(pk=entry_id, clinic_id=clinic_id)
        .first()
    )
    if entry is None:
        raise PermissionDenied
    if entry.status != WaitlistStatus.WAITING:
        raise ValidationError("Somente entradas aguardando podem ser canceladas.")
    entry.status = WaitlistStatus.CANCELED
    entry.save(update_fields=("status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="waitlist_entry",
        resource_id=str(entry.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return entry


@transaction.atomic
def fill_waitlist_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    entry_id: UUID,
    appointment_id: UUID,
    request_id: UUID,
) -> WaitlistEntry:
    """Fill a canceled slot with a waiting entry after human confirmation.

    The appointment must be in a state that permits filling (requested or
    confirmed) and must not already be linked to another waitlist entry.
    """
    _require_reception_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    entry = (
        WaitlistEntry.infrastructure_objects.select_for_update()
        .filter(pk=entry_id, clinic_id=clinic_id)
        .first()
    )
    if entry is None:
        raise PermissionDenied
    if entry.status != WaitlistStatus.WAITING:
        raise ValidationError("Somente entradas aguardando podem ser encaixadas.")
    appointment = (
        Appointment.infrastructure_objects.select_for_update()
        .filter(pk=appointment_id, clinic_id=clinic_id)
        .first()
    )
    if appointment is None:
        raise PermissionDenied
    if appointment.status not in {
        AppointmentStatus.REQUESTED,
        AppointmentStatus.CONFIRMED,
    }:
        raise ValidationError("A consulta não está disponível para encaixe.")
    if WaitlistEntry.infrastructure_objects.filter(
        clinic_id=clinic_id, filled_appointment_id=appointment.pk
    ).exists():
        raise ValidationError("Esta consulta já foi preenchida por outra entrada.")
    entry.status = WaitlistStatus.FILLED
    entry.filled_appointment_id = appointment.pk
    entry.save(update_fields=("status", "filled_appointment", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="waitlist_entry",
        resource_id=str(entry.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return entry
