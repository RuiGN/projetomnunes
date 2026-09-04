"""Authorization policies for physical activity, wellness, and crisis (8.15)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy
from people.selectors import patient_profile_for_user
from wellness.models import RelapsePlanShare


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
    """Wellness domain authorization policy."""

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


def can_manage_patient_wellness(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if the user is authorized to manage their wellness logs and goals."""
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


def can_view_patient_wellness(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if the user can view patient activity and wellness self-reports."""
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


def can_approve_movement_plan(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Check if user is a licensed healthcare professional to sign plans."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    )


def can_access_relapse_plan(
    *,
    user: AbstractBaseUser,
    clinic_id: UUID,
    relapse_plan_id: UUID,
    patient_profile_id: UUID,
) -> bool:
    """Check if user owns relapse plan or holds an active unrevoked share."""
    if not user.is_authenticated or not user.is_active:
        return False

    patient_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=user.pk)
    if patient_profile and patient_profile.id == patient_profile_id:
        return True

    now = timezone.now()
    has_active_share = (
        RelapsePlanShare.objects.for_clinic(clinic_id)
        .filter(
            relapse_plan_id=relapse_plan_id,
            recipient_user_id=user.pk,
            valid_until__gte=now,
            is_revoked=False,
        )
        .exists()
    )
    return has_active_share


__all__ = [
    "AuthorizationPolicy",
    "can_access_relapse_plan",
    "can_approve_movement_plan",
    "can_manage_patient_wellness",
    "can_view_patient_wellness",
]
