"""Authorization policies for support network (8.16)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy
from people.selectors import patient_profile_for_user
from support_network.contracts import (
    FORBIDDEN_SUPPORT_SCOPES,
    GuardianVerificationStatus,
)
from support_network.guardian_models import LegalGuardianConsent
from support_network.network_models import SupportNetworkPermission


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
    """Support network domain authorization policy."""

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


def can_manage_support_network(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if the user can invite supporters or edit permissions."""
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


def can_view_support_network(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if user can view support network structure."""
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


def can_supporter_access_scope(
    *,
    user: AbstractBaseUser,
    clinic_id: UUID,
    patient_profile_id: UUID,
    requested_scope: str,
) -> bool:
    """Check granular permission scope for a supporter.

    STRICT GUARANTEE: Clinical notes, medical records, and diagnostic evaluations
    are NEVER accessible via support network relationships.
    """
    if not user.is_authenticated or not user.is_active:
        return False

    if requested_scope.lower() in FORBIDDEN_SUPPORT_SCOPES:
        return False

    return (
        SupportNetworkPermission.objects.for_clinic(clinic_id)
        .filter(
            relationship__patient_id=patient_profile_id,
            relationship__supporter_user_id=user.pk,
            relationship__is_active=True,
            permission_scope=requested_scope,
            is_active=True,
        )
        .exists()
    )


def can_manage_minor_guardian(
    *, user: AbstractBaseUser, clinic_id: UUID, minor_patient_id: UUID
) -> bool:
    """Check if user is a verified legal guardian or professional."""
    if not user.is_authenticated or not user.is_active:
        return False

    if _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    ):
        return True

    now = timezone.now()
    return (
        LegalGuardianConsent.objects.for_clinic(clinic_id)
        .filter(
            minor_patient_id=minor_patient_id,
            guardian_user_id=user.pk,
            verification_status=GuardianVerificationStatus.VERIFIED.value,
            revoked_at__isnull=True,
        )
        .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
        .exists()
    )


def can_manage_spirituality(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if user can update spirituality preferences."""
    if not user.is_authenticated or not user.is_active:
        return False

    patient_profile = patient_profile_for_user(clinic_id=clinic_id, user_id=user.pk)
    return bool(patient_profile and patient_profile.id == patient_profile_id)


def can_manage_urgent_plan(
    *, user: AbstractBaseUser, clinic_id: UUID, patient_profile_id: UUID
) -> bool:
    """Check if user can update urgent support plan."""
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


__all__ = [
    "AuthorizationPolicy",
    "can_manage_minor_guardian",
    "can_manage_spirituality",
    "can_manage_support_network",
    "can_manage_urgent_plan",
    "can_supporter_access_scope",
    "can_view_support_network",
]
