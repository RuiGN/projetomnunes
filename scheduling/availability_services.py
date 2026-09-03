"""Transactional services for professional availability management."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .models import (
    AvailabilityOverride,
    AvailabilityPattern,
    ScheduleBlock,
    Unit,
)

__all__ = [
    "Service",
    "create_availability_block",
    "create_availability_override",
    "create_availability_pattern",
    "deactivate_availability_pattern",
]


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


def _require_active_therapist(*, clinic_id: UUID, professional_id: UUID) -> None:
    from django.utils import timezone

    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=professional_id,
        role="therapist",
        on_date=timezone.localdate(),
    ):
        raise ValidationError(
            "O profissional não possui vínculo ativo como terapeuta nesta clínica."
        )


@transaction.atomic
def create_availability_pattern(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    professional_id: UUID,
    unit_id: UUID,
    room_id: UUID | None,
    weekday: int,
    start_time: time,
    end_time: time,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> AvailabilityPattern:
    """Create one recurring weekly availability window for a professional."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    _require_active_therapist(clinic_id=clinic_id, professional_id=professional_id)
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    if not 0 <= weekday <= 6:
        raise ValidationError("Dia da semana inválido.")
    if start_time >= end_time:
        raise ValidationError("O horário inicial deve ser anterior ao final.")
    if valid_until is not None and valid_until < valid_from:
        raise ValidationError("A data final não pode ser anterior à inicial.")
    pattern = AvailabilityPattern.infrastructure_objects.create(
        clinic_id=clinic_id,
        professional_id=professional_id,
        unit_id=unit.pk,
        room_id=room_id,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="availability_pattern",
        resource_id=str(pattern.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return pattern


@transaction.atomic
def deactivate_availability_pattern(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    pattern_id: UUID,
    request_id: UUID,
) -> AvailabilityPattern:
    """Deactivate one recurring availability window."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    pattern = (
        AvailabilityPattern.infrastructure_objects.select_for_update()
        .filter(pk=pattern_id, clinic_id=clinic_id)
        .first()
    )
    if pattern is None:
        raise PermissionDenied
    pattern.is_active = False
    pattern.save(update_fields=("is_active", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="availability_pattern",
        resource_id=str(pattern.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return pattern


@transaction.atomic
def create_availability_override(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    professional_id: UUID,
    unit_id: UUID,
    room_id: UUID | None,
    override_date: date,
    start_time: time | None,
    end_time: time | None,
    available: bool,
    reason: str,
    request_id: UUID,
) -> AvailabilityOverride:
    """Create one one-off availability exception for a specific date."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    _require_active_therapist(clinic_id=clinic_id, professional_id=professional_id)
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    if start_time is not None and end_time is not None and start_time >= end_time:
        raise ValidationError("O horário inicial deve ser anterior ao final.")
    override = AvailabilityOverride.infrastructure_objects.create(
        clinic_id=clinic_id,
        professional_id=professional_id,
        unit_id=unit.pk,
        room_id=room_id,
        date=override_date,
        start_time=start_time,
        end_time=end_time,
        available=available,
        reason=reason.strip(),
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="availability_override",
        resource_id=str(override.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return override


@transaction.atomic
def create_availability_block(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    professional_id: UUID,
    unit_id: UUID,
    room_id: UUID | None,
    start_at: datetime,
    end_at: datetime,
    reason: str,
    request_id: UUID,
) -> ScheduleBlock:
    """Create one non-recurring blocking window that removes availability."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    _require_active_therapist(clinic_id=clinic_id, professional_id=professional_id)
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    if end_at <= start_at:
        raise ValidationError("O horário final deve ser posterior ao inicial.")
    block = ScheduleBlock.infrastructure_objects.create(
        clinic_id=clinic_id,
        professional_id=professional_id,
        unit_id=unit.pk,
        room_id=room_id,
        start_at=start_at,
        end_at=end_at,
        reason=reason.strip(),
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="schedule_block",
        resource_id=str(block.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return block
