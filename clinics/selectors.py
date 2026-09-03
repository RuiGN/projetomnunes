"""Tenant-scoped read selectors for the clinics domain."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from core.policies import current_actor_is_active
from core.selectors import Selector as Selector

from .forms import WEEKDAYS
from .models import (
    Clinic,
    ClinicConfiguration,
    ClinicMembership,
    ClinicMembershipQuerySet,
)
from .policies import ClinicAuthorizationPolicy


def active_clinics_for_actor(actor: AbstractBaseUser) -> list[Clinic]:
    """Return active clinics backed by the actor's current memberships only."""
    if not current_actor_is_active(actor):
        return []
    memberships = (
        ClinicMembership.infrastructure_objects.get_queryset()
        .active_on(timezone.localdate())
        .filter(user_id=actor.pk, clinic__is_active=True)
        .select_related("clinic")
        .order_by("clinic__name", "clinic_id")
    )
    return [membership.clinic for membership in memberships]


def active_clinic_ids_for_actor(actor: AbstractBaseUser) -> list[UUID]:
    """Return current active tenant identifiers without exposing memberships."""
    if not current_actor_is_active(actor):
        return []
    return list(
        ClinicMembership.infrastructure_objects.get_queryset()
        .active_on(timezone.localdate())
        .filter(user_id=actor.pk, clinic__is_active=True)
        .values_list("clinic_id", flat=True)
    )


def subject_has_clinic_relationship(*, clinic_id: UUID, subject_id: UUID) -> bool:
    """Return whether the identity has a durable membership in the clinic."""
    return (
        ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=subject_id)
        .exists()
    )


def subject_has_active_clinic_relationship(
    *, clinic_id: UUID, subject_id: UUID, on_date: date | None = None
) -> bool:
    """Return whether the identity has a currently active clinic membership."""
    effective_date = on_date or timezone.localdate()
    return (
        ClinicMembership.objects.for_clinic(clinic_id)
        .active_on(effective_date)
        .filter(user_id=subject_id, clinic__is_active=True)
        .exists()
    )


def active_membership_roles_for_users(
    *, clinic_id: UUID, user_ids: Iterable[UUID], on_date: date
) -> dict[UUID, str]:
    """Expose only current role values needed for cross-domain link validation."""
    return dict(
        ClinicMembership.objects.for_clinic(clinic_id)
        .active_on(on_date)
        .filter(user_id__in=tuple(user_ids), clinic__is_active=True)
        .values_list("user_id", "role")
    )


def actor_has_active_role(actor: AbstractBaseUser, *, role: str) -> bool:
    """Return whether an active identity currently holds the requested role."""
    if not current_actor_is_active(actor):
        return False
    today = timezone.localdate()
    return (
        ClinicMembership.infrastructure_objects.get_queryset()
        .active_on(today)
        .filter(user_id=actor.pk, clinic__is_active=True, role=role)
        .exists()
    )


def active_member_identity_for_role(
    *, clinic_id: UUID, user_id: UUID, role: str
) -> AbstractBaseUser | None:
    """Resolve one current member identity without exposing membership internals."""
    membership = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .active_on(timezone.localdate())
        .filter(user_id=user_id, role=role, clinic__is_active=True)
        .select_related("user")
        .first()
    )
    return membership.user if membership is not None else None


def membership_export_records(
    *, clinic_id: UUID, subject_id: UUID
) -> list[dict[str, object]]:
    """Return only the subject's memberships inside one explicit clinic."""
    if not subject_has_clinic_relationship(
        clinic_id=clinic_id,
        subject_id=subject_id,
    ):
        return []
    memberships = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=subject_id)
        .order_by("valid_from", "id")
        .values("role", "is_active", "valid_from", "valid_until")
    )
    return [
        {
            "type": "clinic_membership",
            "clinic": str(clinic_id),
            "role": item["role"],
            "is_active": item["is_active"],
            "valid_from": item["valid_from"].isoformat(),
            "valid_until": (
                item["valid_until"].isoformat()
                if item["valid_until"] is not None
                else None
            ),
        }
        for item in memberships
    ]


def memberships_visible_to(
    actor: AbstractBaseUser,
    clinic: Clinic,
) -> ClinicMembershipQuerySet:
    """Enumerate memberships only inside an authorized explicit clinic."""
    scoped = ClinicMembership.objects.for_clinic(clinic.pk)
    if not ClinicAuthorizationPolicy().is_allowed(
        actor, clinic, "membership.enumerate"
    ):
        return scoped.none()
    return scoped.select_related("user", "clinic")


def clinic_setup_complete(*, clinic_id: UUID) -> bool:
    """Return whether the clinic finished its ordered setup stages."""
    configuration = ClinicConfiguration.objects.for_clinic(clinic_id).first()
    if configuration is None:
        return False
    expected_days = {day for day, _label in WEEKDAYS}
    if (
        not configuration.service_channels
        or set(configuration.weekly_hours) != expected_days
    ):
        return False
    if not configuration.logo:
        return False
    return configuration.modules_updated_at is not None


def has_non_patient_memberships(*, clinic_id: UUID) -> bool:
    """Return whether any professional or administrative membership exists."""
    return (
        ClinicMembership.objects.for_clinic(clinic_id).exclude(role="patient").exists()
    )


def has_clinic_admin_membership(*, clinic_id: UUID) -> bool:
    """Return whether at least one administrator role is configured."""
    return (
        ClinicMembership.objects.for_clinic(clinic_id)
        .filter(role="clinic_admin")
        .exists()
    )


@dataclass(frozen=True, slots=True)
class ClinicOperatingHours:
    """Minimized operating-hours configuration exposed to other domains."""

    weekly_hours: dict[str, list[dict[str, str]]]
    out_of_hours_instructions: str
    timezone_name: str


def clinic_operating_hours(*, clinic_id: UUID) -> ClinicOperatingHours | None:
    """Return one clinic's configured weekly hours without exposing internals."""
    configuration = ClinicConfiguration.objects.for_clinic(clinic_id).first()
    if configuration is None:
        return None
    return ClinicOperatingHours(
        weekly_hours=configuration.weekly_hours,
        out_of_hours_instructions=configuration.out_of_hours_instructions,
        timezone_name=configuration.timezone_name,
    )


__all__ = [
    "ClinicOperatingHours",
    "Selector",
    "active_clinic_ids_for_actor",
    "active_clinics_for_actor",
    "active_member_identity_for_role",
    "active_membership_roles_for_users",
    "clinic_operating_hours",
    "clinic_setup_complete",
    "has_clinic_admin_membership",
    "has_non_patient_memberships",
    "membership_export_records",
    "memberships_visible_to",
    "subject_has_clinic_relationship",
    "subject_has_active_clinic_relationship",
]
