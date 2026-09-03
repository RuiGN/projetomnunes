"""Central authorization policy for clinic-owned actions."""

from datetime import date
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from core.policies import AuthorizationPolicy as AuthorizationPolicy
from core.policies import current_actor_is_active

from .models import Clinic, ClinicMembership

ACTION_ROLES: dict[str, frozenset[str]] = {
    "clinic.read": frozenset({"clinic_admin", "therapist", "administrative_staff"}),
    "clinic.manage": frozenset({"clinic_admin"}),
    "professionals.manage": frozenset({"clinic_admin"}),
    "patients.create": frozenset({"clinic_admin", "administrative_staff"}),
    "care_relationship.manage": frozenset({"clinic_admin"}),
    "patient.demographics.read": frozenset(
        {"clinic_admin", "therapist", "administrative_staff"}
    ),
    "patient.clinical.read": frozenset({"therapist"}),
    "audit.read": frozenset({"clinic_admin"}),
    "invitation.issue": frozenset({"clinic_admin"}),
    "invitation.revoke": frozenset({"clinic_admin"}),
    "membership.enumerate": frozenset({"clinic_admin"}),
    "membership.update": frozenset({"clinic_admin"}),
    "mfa.reset": frozenset({"clinic_admin"}),
    "course.enroll": frozenset(
        {"clinic_admin", "therapist", "administrative_staff", "patient"}
    ),
}


class ClinicAuthorizationPolicy:
    """Authorize an actor, clinic and stable action; deny unknown actions."""

    def is_allowed(
        self,
        actor: AbstractBaseUser,
        clinic: Clinic,
        action: str,
    ) -> bool:
        """Return a current membership-based, deny-by-default decision."""
        allowed_roles = ACTION_ROLES.get(action)
        if (
            allowed_roles is None
            or not current_actor_is_active(actor)
            or not Clinic.infrastructure_objects.filter(
                pk=clinic.pk, is_active=True
            ).exists()
        ):
            return False

        return (
            ClinicMembership.objects.for_clinic(clinic.pk)
            .active_on(timezone.localdate())
            .filter(user_id=actor.pk, role__in=allowed_roles)
            .exists()
        )


def has_active_clinic_role(
    *, clinic_id: UUID, user_id: UUID, role: str, on_date: date
) -> bool:
    """Expose a minimized current-role decision to authorized domain consumers."""
    return (
        ClinicMembership.objects.for_clinic(clinic_id)
        .active_on(on_date)
        .filter(
            clinic__is_active=True,
            user_id=user_id,
            user__is_active=True,
            role=role,
        )
        .exists()
    )


__all__ = [
    "AuthorizationPolicy",
    "ClinicAuthorizationPolicy",
    "has_active_clinic_role",
]
