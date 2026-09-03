"""Central clinic authorization and cross-tenant isolation tests."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from clinics.policies import ClinicAuthorizationPolicy
from clinics.selectors import memberships_visible_to
from clinics.services import update_membership_role

pytestmark = pytest.mark.django_db


def create_user(username: str) -> User:
    """Create a minimal actor."""
    return User.objects.create_user(email=f"{username}@example.test")


def create_clinic(slug: str) -> Clinic:
    """Create a clinic through infrastructure access."""
    return Clinic.infrastructure_objects.create(name=slug, slug=slug)


def create_membership(
    user: User,
    clinic: Clinic,
    *,
    role: str,
    is_active: bool = True,
) -> ClinicMembership:
    """Create a currently dated membership."""
    return ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic,
        role=role,
        is_active=is_active,
        valid_from=date.today(),
    )


def test_policy_accepts_actor_clinic_action_and_denies_unknown_actions() -> None:
    """The central policy is explicit and deny-by-default."""
    actor = create_user("admin")
    clinic = create_clinic("policy")
    create_membership(actor, clinic, role="clinic_admin")
    policy = ClinicAuthorizationPolicy()

    assert policy.is_allowed(actor, clinic, "clinic.read") is True
    assert policy.is_allowed(actor, clinic, "membership.enumerate") is True
    assert policy.is_allowed(actor, clinic, "membership.update") is True
    assert policy.is_allowed(actor, clinic, "future.unknown") is False


def test_regular_member_cannot_enumerate_or_update_memberships() -> None:
    """Stable roles already enforce least privilege for sensitive actions."""
    actor = create_user("member")
    clinic = create_clinic("member-policy")
    create_membership(actor, clinic, role="therapist")
    policy = ClinicAuthorizationPolicy()

    assert policy.is_allowed(actor, clinic, "clinic.read") is True
    assert policy.is_allowed(actor, clinic, "membership.enumerate") is False
    assert policy.is_allowed(actor, clinic, "membership.update") is False


def test_inactive_membership_is_denied_by_policy() -> None:
    """A stored role grants nothing when its membership is inactive."""
    actor = create_user("inactive")
    clinic = create_clinic("inactive-policy")
    create_membership(actor, clinic, role="clinic_admin", is_active=False)
    policy = ClinicAuthorizationPolicy()

    assert policy.is_allowed(actor, clinic, "clinic.read") is False
    assert policy.is_allowed(actor, clinic, "membership.enumerate") is False


def test_inactive_actor_is_denied_by_policy() -> None:
    """An inactive user receives no permissions from an active membership."""
    actor = create_user("inactive-actor")
    clinic = create_clinic("inactive-actor-policy")
    create_membership(actor, clinic, role="clinic_admin")
    actor.is_active = False
    actor.save(update_fields=("is_active",))

    assert (
        ClinicAuthorizationPolicy().is_allowed(actor, clinic, "membership.update")
        is False
    )


def test_policy_rechecks_stale_actor_active_state_from_database() -> None:
    """A stale active user instance grants no permissions after deactivation."""
    actor = create_user("stale-inactive-policy-actor")
    clinic = create_clinic("stale-inactive-policy")
    create_membership(actor, clinic, role="clinic_admin")
    User.objects.filter(pk=actor.pk).update(is_active=False)

    assert actor.is_active is True
    assert (
        ClinicAuthorizationPolicy().is_allowed(actor, clinic, "membership.update")
        is False
    )


def test_policy_denies_deleted_stale_actor_without_target_change() -> None:
    """A deleted actor instance cannot authorize or mutate a target membership."""
    actor = create_user("stale-deleted-policy-actor")
    clinic = create_clinic("stale-deleted-policy")
    create_membership(actor, clinic, role="clinic_admin")
    target = create_membership(
        create_user("stale-deleted-policy-target"), clinic, role="therapist"
    )
    expected_updated_at = target.updated_at
    User.objects.filter(pk=actor.pk).delete()

    assert actor.pk is not None
    assert (
        ClinicAuthorizationPolicy().is_allowed(actor, clinic, "membership.update")
        is False
    )
    target.refresh_from_db()
    assert target.role == "therapist"
    assert target.updated_at == expected_updated_at


def test_policy_rechecks_stale_clinic_active_state_from_database() -> None:
    """A stale active instance cannot authorize a deactivated tenant."""
    actor = create_user("stale-clinic-actor")
    clinic = create_clinic("stale-clinic-policy")
    create_membership(actor, clinic, role="clinic_admin")
    Clinic.infrastructure_objects.filter(pk=clinic.pk).update(is_active=False)

    assert clinic.is_active is True
    assert (
        ClinicAuthorizationPolicy().is_allowed(actor, clinic, "membership.update")
        is False
    )


def test_cross_tenant_membership_enumeration_returns_only_request_clinic() -> None:
    """An administrator in clinic A cannot enumerate clinic B records."""
    actor = create_user("actor")
    member_a = create_user("member-a")
    member_b = create_user("member-b")
    clinic_a = create_clinic("tenant-a")
    clinic_b = create_clinic("tenant-b")
    actor_membership = create_membership(actor, clinic_a, role="clinic_admin")
    membership_a = create_membership(member_a, clinic_a, role="therapist")
    membership_b = create_membership(member_b, clinic_b, role="therapist")

    visible = memberships_visible_to(actor, clinic_a)

    assert set(visible) == {actor_membership, membership_a}
    assert membership_b not in visible


def test_unauthorized_actor_cannot_enumerate_memberships() -> None:
    """Enumeration returns no records rather than exposing another tenant."""
    actor = create_user("outsider")
    clinic = create_clinic("private")
    create_membership(create_user("inside"), clinic, role="clinic_admin")

    assert list(memberships_visible_to(actor, clinic)) == []


def test_authorized_same_tenant_membership_update_succeeds() -> None:
    """A clinic administrator can update a membership in the request clinic."""
    actor = create_user("same-tenant-updater")
    clinic = create_clinic("same-tenant-update")
    create_membership(actor, clinic, role="clinic_admin")
    target = create_membership(
        create_user("same-tenant-target"), clinic, role="therapist"
    )

    updated = update_membership_role(
        actor=actor,
        clinic=clinic,
        membership_id=target.pk,
        role="clinic_admin",
    )

    assert updated.role == "clinic_admin"
    target.refresh_from_db()
    assert target.role == "clinic_admin"


def test_membership_role_update_advances_updated_at() -> None:
    """A role change follows model save semantics and advances updated_at."""
    actor = create_user("timestamp-updater")
    clinic = create_clinic("timestamp-update")
    create_membership(actor, clinic, role="clinic_admin")
    target = create_membership(
        create_user("timestamp-target"), clinic, role="therapist"
    )
    previous_updated_at = timezone.now() - timedelta(days=1)
    ClinicMembership.infrastructure_objects.filter(pk=target.pk).update(
        updated_at=previous_updated_at
    )

    updated = update_membership_role(
        actor=actor,
        clinic=clinic,
        membership_id=target.pk,
        role="clinic_admin",
    )

    assert updated.updated_at > previous_updated_at


def test_cross_tenant_membership_update_is_denied_and_unchanged() -> None:
    """An authorized clinic A action cannot target a clinic B membership ID."""
    actor = create_user("updater")
    clinic_a = create_clinic("update-a")
    clinic_b = create_clinic("update-b")
    create_membership(actor, clinic_a, role="clinic_admin")
    target = create_membership(create_user("target"), clinic_b, role="therapist")

    with pytest.raises(PermissionDenied):
        update_membership_role(
            actor=actor,
            clinic=clinic_a,
            membership_id=target.pk,
            role="clinic_admin",
        )

    target.refresh_from_db()
    assert target.role == "therapist"


def test_stale_deactivated_actor_cannot_update_membership() -> None:
    """Update authorization rechecks a stale actor against the user table."""
    actor = create_user("stale-inactive-updater")
    clinic = create_clinic("stale-inactive-update")
    create_membership(actor, clinic, role="clinic_admin")
    target = create_membership(
        create_user("stale-inactive-target"), clinic, role="therapist"
    )
    User.objects.filter(pk=actor.pk).update(is_active=False)

    assert actor.is_active is True
    with pytest.raises(PermissionDenied):
        update_membership_role(
            actor=actor,
            clinic=clinic,
            membership_id=target.pk,
            role="clinic_admin",
        )

    target.refresh_from_db()
    assert target.role == "therapist"


def test_stale_deleted_actor_cannot_update_membership_or_change_target() -> None:
    """Membership updates deny a deleted stale actor before changing the target."""
    actor = create_user("stale-deleted-updater")
    clinic = create_clinic("stale-deleted-update")
    create_membership(actor, clinic, role="clinic_admin")
    target = create_membership(
        create_user("stale-deleted-update-target"), clinic, role="therapist"
    )
    expected_updated_at = target.updated_at
    User.objects.filter(pk=actor.pk).delete()

    assert actor.pk is not None
    with pytest.raises(PermissionDenied):
        update_membership_role(
            actor=actor,
            clinic=clinic,
            membership_id=target.pk,
            role="clinic_admin",
        )

    target.refresh_from_db()
    assert target.role == "therapist"
    assert target.updated_at == expected_updated_at


def test_regular_member_update_is_denied_and_unchanged() -> None:
    """Tenant scope alone does not bypass action authorization."""
    actor = create_user("regular-updater")
    target_user = create_user("regular-target")
    clinic = create_clinic("regular-update")
    create_membership(actor, clinic, role="therapist")
    target = create_membership(target_user, clinic, role="therapist")

    with pytest.raises(PermissionDenied):
        update_membership_role(
            actor=actor,
            clinic=clinic,
            membership_id=target.pk,
            role="clinic_admin",
        )

    target.refresh_from_db()
    assert target.role == "therapist"


def test_regular_member_cannot_elevate_own_role() -> None:
    actor = create_user("self-elevation")
    clinic = create_clinic("self-elevation")
    membership = create_membership(actor, clinic, role="therapist")

    with pytest.raises(PermissionDenied):
        update_membership_role(
            actor=actor,
            clinic=clinic,
            membership_id=membership.pk,
            role="clinic_admin",
        )

    membership.refresh_from_db()
    assert membership.role == "therapist"
