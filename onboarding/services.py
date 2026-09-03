"""Transactional services for the onboarding domain."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import patient_profile_for_user

from .models import PatientOnboarding

__all__ = [
    "Service",
    "complete_patient_onboarding",
    "record_patient_onboarding",
]


def _authorize_patient(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    """Require an active patient membership for self-service onboarding."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied


@transaction.atomic
def record_patient_onboarding(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    goals: list[str],
    contact_preferences: dict[str, Any],
    reminder_windows: dict[str, Any],
    current_step: str,
    request_id: UUID,
) -> PatientOnboarding:
    """Save or resume one patient's declared onboarding data."""
    del request_id
    _authorize_patient(clinic_id=clinic_id, actor=actor)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None or profile.pk != patient_profile_id:
        raise PermissionDenied
    if current_step not in PatientOnboarding.Step.values:
        raise ValidationError("Etapa de onboarding inválida.")
    normalized_goals = [item.strip() for item in goals if item and item.strip()]
    onboarding, _created = (
        PatientOnboarding.infrastructure_objects.select_for_update().get_or_create(
            clinic_id=clinic_id,
            patient_profile=profile,
            defaults={
                "goals": [],
                "contact_preferences": {},
                "reminder_windows": {},
                "current_step": PatientOnboarding.Step.GOALS,
            },
        )
    )
    onboarding.goals = normalized_goals
    onboarding.contact_preferences = contact_preferences
    onboarding.reminder_windows = reminder_windows
    onboarding.current_step = current_step
    if (
        current_step == PatientOnboarding.Step.COMPLETE
        and onboarding.completed_at is None
    ):
        onboarding.completed_at = timezone.now()
    onboarding.full_clean(validate_unique=False, validate_constraints=False)
    onboarding.save()
    return onboarding


@transaction.atomic
def complete_patient_onboarding(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    request_id: UUID,
) -> PatientOnboarding:
    """Mark one patient's onboarding complete after reviewing terms."""
    del request_id
    _authorize_patient(clinic_id=clinic_id, actor=actor)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None or profile.pk != patient_profile_id:
        raise PermissionDenied
    onboarding = (
        PatientOnboarding.infrastructure_objects.select_for_update()
        .filter(clinic_id=clinic_id, patient_profile=profile)
        .first()
    )
    if onboarding is None:
        raise PermissionDenied
    onboarding.current_step = PatientOnboarding.Step.COMPLETE
    onboarding.completed_at = timezone.now()
    onboarding.save(update_fields=("current_step", "completed_at", "updated_at"))
    return onboarding
