"""Transactional services for the low-energy mode."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import patient_profile_for_user

from .low_energy_models import LowEnergyActionTemplate, LowEnergyMode

__all__ = [
    "Service",
    "activate_low_energy_mode",
    "configure_low_energy_actions",
    "deactivate_low_energy_mode",
    "expire_stale_low_energy_sessions",
    "get_low_energy_state",
]

MAX_SESSION_HOURS = 24
DEFAULT_SESSION_HOURS = 8


def _patient_profile_id_for(clinic_id: UUID, actor: AbstractBaseUser) -> UUID:
    """Authorize self-service access and return the actor's own profile id."""
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


def get_low_energy_state(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> LowEnergyMode | None:
    """Return the patient's currently active low-energy session, if any."""
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        return None
    now = timezone.now()
    session = (
        LowEnergyMode.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=profile.pk,
            ended_at__isnull=True,
            started_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("-started_at")
        .first()
    )
    return session


@transaction.atomic
def configure_low_energy_actions(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    action_1: str = "",
    action_2: str = "",
    action_3: str = "",
    request_id: UUID,
) -> LowEnergyActionTemplate:
    """Save a versioned set of up to three minimal actions (8.7.3.1)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    actions = [action_1.strip()[:255], action_2.strip()[:255], action_3.strip()[:255]]
    if not any(actions):
        raise ValidationError("Configure pelo menos uma ação mínima.")

    previous = (
        LowEnergyActionTemplate.infrastructure_objects.filter(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            is_active=True,
        )
        .select_for_update()
        .order_by("-version")
        .first()
    )
    next_version = (previous.version + 1) if previous else 1
    if previous is not None:
        previous.is_active = False
        previous.save(update_fields=("is_active", "updated_at"))

    template = LowEnergyActionTemplate(
        clinic_id=clinic_id,
        patient_profile_id=profile_id,
        author_id=actor.pk,
        is_active=True,
        version=next_version,
        action_1=actions[0],
        action_2=actions[1],
        action_3=actions[2],
    )
    template.full_clean(validate_unique=False, validate_constraints=False)
    template.save(force_insert=True)
    return template


@transaction.atomic
def activate_low_energy_mode(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    duration_hours: int = DEFAULT_SESSION_HOURS,
    note: str = "",
    request_id: UUID,
) -> LowEnergyMode:
    """One-touch activation using the patient's configured actions (8.7.3.2)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)

    existing = get_low_energy_state(clinic_id=clinic_id, actor=actor)
    if existing is not None:
        return existing

    template = (
        LowEnergyActionTemplate.infrastructure_objects.filter(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )
    if template is None:
        raise ValidationError(
            "Configure suas ações mínimas antes de ativar o modo baixa energia."
        )

    duration_hours = max(1, min(int(duration_hours), MAX_SESSION_HOURS))
    now = timezone.now()
    session = LowEnergyMode(
        clinic_id=clinic_id,
        patient_profile_id=profile_id,
        author_id=actor.pk,
        action_1=template.action_1,
        action_2=template.action_2,
        action_3=template.action_3,
        note=note.strip()[:500],
        suppress_non_essential_notifications=True,
        started_at=now,
        ends_at=now + timedelta(hours=duration_hours),
        end_reason="",
    )
    session.full_clean(validate_unique=False, validate_constraints=False)
    session.save(force_insert=True)
    return session


@transaction.atomic
def deactivate_low_energy_mode(
    *, clinic_id: UUID, actor: AbstractBaseUser, request_id: UUID
) -> LowEnergyMode | None:
    """Manual end of the low-energy period (8.7.3.4)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    session = (
        LowEnergyMode.infrastructure_objects.select_for_update()
        .filter(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            ended_at__isnull=True,
        )
        .order_by("-started_at")
        .first()
    )
    if session is None:
        return None
    session.ended_at = timezone.now()
    session.end_reason = "manual"
    session.save(update_fields=("ended_at", "end_reason", "updated_at"))
    return session


@transaction.atomic
def expire_stale_low_energy_sessions(clinic_id: UUID | None = None) -> int:
    """Auto-expire sessions past their configured end (8.7.3.4)."""
    now = timezone.now()
    queryset = LowEnergyMode.infrastructure_objects.select_for_update().filter(
        ended_at__isnull=True,
        ends_at__lte=now,
    )
    if clinic_id is not None:
        queryset = queryset.filter(clinic_id=clinic_id)
    expired = 0
    for session in queryset:
        session.ended_at = now
        session.end_reason = "expired"
        session.save(update_fields=("ended_at", "end_reason", "updated_at"))
        expired += 1
    return expired


def notifications_allowed(
    *, clinic_id: UUID, patient_profile_id: UUID, essential: bool
) -> bool:
    """Whether one notification may be delivered to the patient now (8.7.3.3).

    Essential entries (consultations and reminders explicitly marked as
    essential) are never suppressed; non-essential ones are suppressed while a
    low-energy session is active.
    """
    if essential:
        return True
    now = timezone.now()
    return (
        not LowEnergyMode.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=patient_profile_id,
            ended_at__isnull=True,
            started_at__lte=now,
            ends_at__gt=now,
            suppress_non_essential_notifications=True,
        )
        .exists()
    )
