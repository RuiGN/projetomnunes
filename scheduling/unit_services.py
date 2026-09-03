"""Transactional services for unit and room administration."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .models import Appointment, Room, Unit

__all__ = [
    "Service",
    "create_room",
    "create_unit",
    "deactivate_room",
    "deactivate_unit",
    "update_unit",
]


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


@transaction.atomic
def create_unit(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    name: str,
    address: dict[str, object],
    timezone_name: str,
    request_id: UUID,
) -> Unit:
    """Create one physical unit for a clinic."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized = name.strip()
    if not normalized:
        raise ValidationError("Informe o nome da unidade.")
    if Unit.infrastructure_objects.filter(
        clinic_id=clinic_id, name=normalized
    ).exists():
        raise ValidationError("Já existe uma unidade com este nome.")
    unit = Unit.infrastructure_objects.create(
        clinic_id=clinic_id,
        name=normalized,
        address=address or {},
        timezone_name=timezone_name or "America/Sao_Paulo",
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="unit",
        resource_id=str(unit.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return unit


@transaction.atomic
def update_unit(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    unit_id: UUID,
    name: str,
    address: dict[str, object],
    timezone_name: str,
    request_id: UUID,
) -> Unit:
    """Update one unit's operational identity."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    unit = (
        Unit.infrastructure_objects.select_for_update()
        .filter(pk=unit_id, clinic_id=clinic_id)
        .first()
    )
    if unit is None:
        raise PermissionDenied
    normalized = name.strip()
    if not normalized:
        raise ValidationError("Informe o nome da unidade.")
    if (
        Unit.infrastructure_objects.filter(clinic_id=clinic_id, name=normalized)
        .exclude(pk=unit.pk)
        .exists()
    ):
        raise ValidationError("Já existe uma unidade com este nome.")
    unit.name = normalized
    unit.address = address or {}
    unit.timezone_name = timezone_name or "America/Sao_Paulo"
    unit.save(update_fields=("name", "address", "timezone_name", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="unit",
        resource_id=str(unit.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return unit


@transaction.atomic
def deactivate_unit(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    unit_id: UUID,
    request_id: UUID,
) -> Unit:
    """Deactivate one unit, blocking when future appointments are linked."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    unit = (
        Unit.infrastructure_objects.select_for_update()
        .filter(pk=unit_id, clinic_id=clinic_id)
        .first()
    )
    if unit is None:
        raise PermissionDenied
    from django.utils import timezone

    if Appointment.infrastructure_objects.filter(
        clinic_id=clinic_id, unit_id=unit.pk, start_at__gte=timezone.now()
    ).exists():
        raise ValidationError(
            "Não é possível inativar uma unidade com consultas futuras vinculadas."
        )
    unit.is_active = False
    unit.save(update_fields=("is_active", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="unit",
        resource_id=str(unit.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return unit


@transaction.atomic
def create_room(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    unit_id: UUID,
    name: str,
    request_id: UUID,
) -> Room:
    """Create one bookable room inside a unit."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    unit = Unit.infrastructure_objects.filter(pk=unit_id, clinic_id=clinic_id).first()
    if unit is None:
        raise ValidationError("Unidade não encontrada.")
    normalized = name.strip()
    if not normalized:
        raise ValidationError("Informe o nome da sala.")
    if Room.infrastructure_objects.filter(
        clinic_id=clinic_id, unit_id=unit.pk, name=normalized
    ).exists():
        raise ValidationError("Já existe uma sala com este nome na unidade.")
    room = Room.infrastructure_objects.create(
        clinic_id=clinic_id, unit_id=unit.pk, name=normalized
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="room",
        resource_id=str(room.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return room


@transaction.atomic
def deactivate_room(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    room_id: UUID,
    request_id: UUID,
) -> Room:
    """Deactivate one room."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    room = (
        Room.infrastructure_objects.select_for_update()
        .filter(pk=room_id, clinic_id=clinic_id)
        .first()
    )
    if room is None:
        raise PermissionDenied
    room.is_active = False
    room.save(update_fields=("is_active", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="room",
        resource_id=str(room.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return room
