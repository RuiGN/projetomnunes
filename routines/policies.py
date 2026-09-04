"""Authorization policies for routines, habits, medications, sleep and care plans."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy
from people.selectors import patient_profile_for_user
from routines.models import MedicationConsentShare


def _user_has_any_clinic_role(
    *, user_id: UUID, clinic_id: UUID, roles: set[str]
) -> bool:
    today = timezone.localdate()
    return any(
        has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            on_date=today,
        )
        for role in roles
    )


class AuthorizationPolicy(CoreAuthorizationPolicy[AbstractBaseUser, Any]):
    """Routines domain authorization policy."""

    def is_allowed(self, subject: AbstractBaseUser, resource: Any, /) -> bool:
        if not subject.is_authenticated or not subject.is_active:
            return False
        clinic_id = getattr(resource, "clinic_id", None)
        if clinic_id is None:
            return False
        return _user_has_any_clinic_role(
            user_id=subject.pk,
            clinic_id=clinic_id,
            roles={"clinic_admin", "therapist", "patient"},
        )


def can_manage_patient_routines(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if the user is authorized to create/edit habits and routine blocks."""
    if not user.is_authenticated or not user.is_active:
        return False

    patient_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=user.pk)
    if patient_profile and patient_profile.id == patient_profile_id:
        return True

    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    )


def can_view_patient_routines(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if user can view patient habits, routines and sleep tracking."""
    if not user.is_authenticated or not user.is_active:
        return False

    patient_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=user.pk)
    if patient_profile and patient_profile.id == patient_profile_id:
        return True

    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    )


def can_view_medication_adherence(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if user is authorized to view medication adherence (requires consent)."""
    if not user.is_authenticated or not user.is_active:
        return False

    patient_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=user.pk)
    if patient_profile and patient_profile.id == patient_profile_id:
        return True

    has_consent = (
        MedicationConsentShare.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=patient_profile_id,
            granted_to_user_id=user.pk,
            is_active=True,
        )
        .exists()
    )

    if has_consent:
        return True

    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_prescribe_care_plan(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Check if the user is a licensed professional authorized to sign care plans."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    )


__all__ = [
    "AuthorizationPolicy",
    "can_manage_patient_routines",
    "can_prescribe_care_plan",
    "can_view_medication_adherence",
    "can_view_patient_routines",
]
