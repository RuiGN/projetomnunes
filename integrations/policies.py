"""Authorization policies for external integrations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy


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
    """Default integration authorization policy."""

    def is_allowed(self, subject: AbstractBaseUser, resource: Any, /) -> bool:
        if not subject.is_authenticated or not subject.is_active:
            return False
        clinic_id = getattr(resource, "clinic_id", None)
        if clinic_id is None:
            return False
        return _user_has_any_clinic_role(
            user_id=subject.pk,
            clinic_id=clinic_id,
            roles={"clinic_admin", "administrative_staff"},
        )


def can_manage_integrations(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Check if the user is authorized to manage clinic integrations."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_view_integrations(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Check if the user is authorized to view clinic integration status/metrics."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "administrative_staff"},
    )


def can_manage_api_clients(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Only clinic admin can manage API clients and rotate secrets."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_manage_webhooks(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Only clinic admin can create webhook subscriptions or replay DLQ."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_import_csv(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Admins and administrative staff can import batch CSV files."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "administrative_staff"},
    )


def can_export_csv(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Only clinic admin can export bulk clinical or patient CSVs."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_manage_wearables(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Admins, clinical staff and professionals can manage patient wearable links."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "administrative_staff", "clinical_director"},
    )


def can_manage_partner_agreements(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Only clinic admin can homologate external partners and DPA agreements."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


def can_manage_rollout(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Only clinic admin can control canary rollout and emergency rollback."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin"},
    )


__all__ = [
    "AuthorizationPolicy",
    "can_export_csv",
    "can_import_csv",
    "can_manage_api_clients",
    "can_manage_integrations",
    "can_manage_partner_agreements",
    "can_manage_rollout",
    "can_manage_wearables",
    "can_manage_webhooks",
    "can_view_integrations",
]
