"""Model and manager contracts for the multi-tenant clinic core."""

from datetime import date, timedelta
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import User
from clinics.models import Clinic, ClinicMembership, TenantScopeRequiredError

pytestmark = pytest.mark.django_db


def create_clinic(*, slug: str = "central") -> Clinic:
    """Create a clinic through the infrastructure-only manager."""
    return Clinic.infrastructure_objects.create(name="Clínica Central", slug=slug)


def create_user(*, username: str = "therapist") -> User:
    """Create a minimal configured user."""
    return User.objects.create_user(email=f"{username}@example.test")


def test_core_models_use_uuid_primary_keys() -> None:
    """User, clinic and membership use UUID primary keys from the first migration."""
    user = create_user()
    clinic = create_clinic()
    membership = ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic,
        role="therapist",
        valid_from=date.today(),
    )

    assert isinstance(user.pk, UUID)
    assert isinstance(clinic.pk, UUID)
    assert isinstance(membership.pk, UUID)


def test_clinic_has_stable_unique_slug_status_and_timestamps() -> None:
    """The tenant root carries its stable identifier and lifecycle metadata."""
    clinic = create_clinic()

    assert clinic.slug == "central"
    assert clinic.is_active is True
    assert clinic.created_at is not None
    assert clinic.updated_at is not None

    with pytest.raises(IntegrityError):
        create_clinic(slug="central")


def test_clinic_slug_cannot_change_after_creation() -> None:
    """The globally unique technical clinic slug remains stable."""
    clinic = create_clinic()
    clinic.slug = "renamed"

    with pytest.raises(ValidationError, match="slug"):
        clinic.save()

    clinic.refresh_from_db()
    assert clinic.slug == "central"


def test_membership_connects_user_with_role_status_validity_and_timestamps() -> None:
    """Membership stores only the current task's tenant authorization facts."""
    today = date.today()
    membership = ClinicMembership.infrastructure_objects.create(
        user=create_user(),
        clinic=create_clinic(),
        role="clinic_admin",
        is_active=True,
        valid_from=today,
        valid_until=today + timedelta(days=30),
    )

    assert membership.role == "clinic_admin"
    assert membership.is_active is True
    assert membership.valid_from == today
    assert membership.valid_until == today + timedelta(days=30)
    assert membership.created_at is not None
    assert membership.updated_at is not None


def test_membership_rejects_duplicate_user_clinic_pair() -> None:
    """A user has at most one membership record per clinic."""
    user = create_user()
    clinic = create_clinic()
    values = {
        "user": user,
        "clinic": clinic,
        "role": "therapist",
        "valid_from": date.today(),
    }
    ClinicMembership.infrastructure_objects.create(**values)

    with pytest.raises(IntegrityError):
        ClinicMembership.infrastructure_objects.create(**values)


def test_membership_rejects_validity_end_before_start() -> None:
    """Database validity ranges cannot end before they begin."""
    today = date.today()

    with pytest.raises(IntegrityError):
        ClinicMembership.infrastructure_objects.create(
            user=create_user(),
            clinic=create_clinic(),
            role="therapist",
            valid_from=today,
            valid_until=today - timedelta(days=1),
        )


def test_default_clinic_manager_requires_explicit_resolution_scope() -> None:
    """Global clinic discovery is unavailable outside infrastructure."""
    clinic = create_clinic()

    with pytest.raises(TenantScopeRequiredError):
        Clinic.objects.all()

    assert list(Clinic.objects.for_clinic(clinic.pk)) == [clinic]
    assert Clinic._meta.default_manager_name == "objects"
    assert Clinic._meta.base_manager_name == "infrastructure_objects"


def test_default_membership_manager_requires_explicit_clinic_scope() -> None:
    """The public default manager has no convenient unscoped query path."""
    clinic = create_clinic()
    membership = ClinicMembership.infrastructure_objects.create(
        user=create_user(),
        clinic=clinic,
        role="therapist",
        valid_from=date.today(),
    )

    with pytest.raises(TenantScopeRequiredError):
        ClinicMembership.objects.all()

    assert list(ClinicMembership.objects.for_clinic(clinic.pk)) == [membership]


def test_scoped_membership_queryset_cannot_read_or_update_other_clinic() -> None:
    """A scoped queryset neither reads nor mutates another tenant's membership."""
    user = create_user()
    clinic_a = create_clinic(slug="clinic-a")
    clinic_b = create_clinic(slug="clinic-b")
    membership_a = ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic_a,
        role="therapist",
        valid_from=date.today(),
    )
    membership_b = ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic_b,
        role="therapist",
        valid_from=date.today(),
    )

    scoped = ClinicMembership.objects.for_clinic(clinic_a.pk)

    assert list(scoped) == [membership_a]
    assert scoped.filter(pk=membership_b.pk).update(role="clinic_admin") == 0
    membership_b.refresh_from_db()
    assert membership_b.role == "therapist"


def test_manager_metadata_makes_safe_and_infrastructure_paths_explicit() -> None:
    """Django internals and callers can distinguish scoped from unrestricted access."""
    metadata = ClinicMembership._meta

    assert metadata.default_manager_name == "objects"
    assert metadata.base_manager_name == "infrastructure_objects"
    assert ClinicMembership._default_manager is ClinicMembership.objects
    assert ClinicMembership._base_manager is ClinicMembership.infrastructure_objects


def test_reverse_membership_relations_do_not_expose_unscoped_querysets() -> None:
    """Reverse user and clinic access retains the tenant-safe default manager."""
    user = create_user()
    clinic = create_clinic()
    ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic,
        role="therapist",
        valid_from=date.today(),
    )

    with pytest.raises(TenantScopeRequiredError):
        user.clinic_memberships.all()
    with pytest.raises(TenantScopeRequiredError):
        clinic.memberships.all()


def test_user_reverse_manager_for_clinic_preserves_user_relation_scope() -> None:
    """A user-bound manager cannot read another user's selected-clinic record."""
    actor = create_user(username="reverse-actor")
    other = create_user(username="reverse-other")
    clinic_a = create_clinic(slug="reverse-user-a")
    clinic_b = create_clinic(slug="reverse-user-b")
    ClinicMembership.infrastructure_objects.create(
        user=actor,
        clinic=clinic_a,
        role="therapist",
        valid_from=date.today(),
    )
    ClinicMembership.infrastructure_objects.create(
        user=other,
        clinic=clinic_b,
        role="therapist",
        valid_from=date.today(),
    )

    assert list(actor.clinic_memberships.for_clinic(clinic_b.pk)) == []


def test_clinic_reverse_manager_for_clinic_preserves_clinic_relation_scope() -> None:
    """A clinic-bound manager cannot switch to another explicit clinic."""
    user = create_user(username="reverse-clinic-user")
    clinic_a = create_clinic(slug="reverse-clinic-a")
    clinic_b = create_clinic(slug="reverse-clinic-b")
    ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic_a,
        role="therapist",
        valid_from=date.today(),
    )
    ClinicMembership.infrastructure_objects.create(
        user=user,
        clinic=clinic_b,
        role="therapist",
        valid_from=date.today(),
    )

    assert list(clinic_a.memberships.for_clinic(clinic_b.pk)) == []
