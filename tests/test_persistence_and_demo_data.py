"""Persistence, constraints, synthetic factories, and demo seed contracts."""

from __future__ import annotations

from datetime import date
from io import StringIO
from uuid import UUID

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership

pytestmark = pytest.mark.django_db


def test_persistence_base_is_abstract_and_timezone_aware() -> None:
    """The public base supplies only UUID identity and lifecycle timestamps."""
    from core.persistence import UUIDTimestampedModel
    from tests.factories import ClinicFactory

    assert UUIDTimestampedModel._meta.abstract is True
    assert UUIDTimestampedModel._meta.get_field("id").primary_key is True
    assert UUIDTimestampedModel._meta.get_field("id").default is not None

    clinic = ClinicFactory.create()

    assert isinstance(clinic.pk, UUID)
    assert timezone.is_aware(clinic.created_at)
    assert timezone.is_aware(clinic.updated_at)
    assert not hasattr(UUIDTimestampedModel, "clinic")
    assert not hasattr(UUIDTimestampedModel, "created_by")


def test_clinic_inherits_persistence_base_and_is_not_demo_by_default() -> None:
    """Ordinary clinics carry the shared persistence fields and explicit demo flag."""
    from core.persistence import UUIDTimestampedModel
    from tests.factories import ClinicFactory

    clinic = ClinicFactory.create()

    assert issubclass(Clinic, UUIDTimestampedModel)
    assert clinic.is_demo is False


def test_clinic_slug_is_case_insensitively_unique() -> None:
    """Slug identity cannot differ only by letter case at the database boundary."""
    from tests.factories import ClinicFactory

    ClinicFactory.create(slug="clinica-exemplo")

    with pytest.raises(IntegrityError):
        ClinicFactory.create(slug="CLINICA-EXEMPLO")


@pytest.mark.parametrize(
    "slug",
    (
        "CLINICA-EXEMPLO",
        "clínica-exemplo",
        "CLÍNICA-EXEMPLO",
        "clinica--exemplo",
        "-clinica-exemplo",
        "clinica-exemplo-",
        "clinica_exemplo",
        "clinica-exemplo ",
        "clinica-exemplo\n",
        "clinica-exemplo\r",
        "clinica-exemplo\t",
    ),
)
def test_database_rejects_noncanonical_clinic_slugs(slug: str) -> None:
    """Every backend accepts only canonical lowercase ASCII clinic slugs."""
    from tests.factories import ClinicFactory

    with pytest.raises(IntegrityError):
        ClinicFactory.create(slug=slug)


@pytest.mark.parametrize("slug", ("clinic", "clinic-2", "2-clinics", "a1-b2-c3"))
def test_database_accepts_canonical_lowercase_ascii_clinic_slugs(slug: str) -> None:
    """The database invariant preserves canonical lowercase ASCII identifiers."""
    from tests.factories import ClinicFactory

    assert ClinicFactory.create(slug=slug).slug == slug


def test_named_schema_invariants_and_indexes_are_declared() -> None:
    """Stable names make clinic and membership schema guarantees reviewable."""
    clinic_constraints = {item.name for item in Clinic._meta.constraints}
    clinic_indexes = {item.name for item in Clinic._meta.indexes}
    membership_constraints = {item.name for item in ClinicMembership._meta.constraints}
    membership_indexes = {item.name for item in ClinicMembership._meta.indexes}

    assert "unique_clinic_slug_case_insensitive" in clinic_constraints
    assert "clinic_slug_canonical_ascii_lowercase" in clinic_constraints
    assert clinic_indexes == {"clinic_active_slug_idx", "clinic_demo_idx"}
    assert membership_constraints == {
        "unique_user_clinic_membership",
        "membership_valid_until_on_or_after_start",
    }
    assert membership_indexes == {
        "membership_clinic_user_idx",
        "membership_prof_list_idx",
        "membership_user_validity_idx",
    }


def test_factories_create_isolated_synthetic_relationships() -> None:
    """Factory defaults never share mutable user, clinic, or membership records."""
    from tests.factories import ClinicMembershipFactory

    first = ClinicMembershipFactory.create()
    second = ClinicMembershipFactory.create()

    assert first.pk != second.pk
    assert first.user_id != second.user_id
    assert first.clinic_id != second.clinic_id
    assert first.clinic.is_demo is False
    assert first.user.email.endswith("@example.test")
    assert first.user.has_usable_password() is False
    assert first.role == ClinicMembership.Role.THERAPIST


def test_membership_factory_respects_explicit_relationships() -> None:
    """Tests can compose one synthetic user and clinic without hidden replacements."""
    from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

    user = UserFactory.create()
    clinic = ClinicFactory.create(name="Clínica Sintética")

    membership = ClinicMembershipFactory.create(
        user=user,
        clinic=clinic,
        role=ClinicMembership.Role.PATIENT,
    )

    assert membership.user == user
    assert membership.clinic == clinic
    assert membership.valid_from == date.today()


def enable_demo_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt in to the guarded command exactly as local development must."""
    monkeypatch.setenv("DJANGO_ENV", "development")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)


def test_seed_demo_is_idempotent_and_marks_reserved_synthetic_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated local seeding converges on one marked clinic and three stable roles."""
    first_output = StringIO()
    second_output = StringIO()

    enable_demo_seed(monkeypatch)
    call_command("seed_demo", stdout=first_output)
    call_command("seed_demo", stdout=second_output)

    clinic = Clinic.infrastructure_objects.get(slug="clinica-demonstracao")
    memberships = list(
        ClinicMembership.infrastructure_objects.filter(clinic=clinic).order_by("role")
    )
    users = list(
        User.objects.filter(clinic_memberships__clinic=clinic).order_by("username")
    )

    assert clinic.name == "Clínica Demonstração"
    assert clinic.is_demo is True
    assert [membership.role for membership in memberships] == [
        ClinicMembership.Role.CLINIC_ADMIN,
        ClinicMembership.Role.PATIENT,
        ClinicMembership.Role.THERAPIST,
    ]
    assert len(users) == 3
    assert all(user.email.endswith("@example.test") for user in users)
    assert all(user.has_usable_password() is False for user in users)
    assert "Dados sintéticos de demonstração prontos." in first_output.getvalue()
    assert "Dados sintéticos de demonstração prontos." in second_output.getvalue()


@pytest.mark.parametrize("environment", (None, "staging", "test", "production"))
def test_seed_demo_refuses_non_development_environments_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    environment: str | None,
) -> None:
    """Absent and non-development environments fail closed before any write."""
    if environment is None:
        monkeypatch.delenv("DJANGO_ENV", raising=False)
    else:
        monkeypatch.setenv("DJANGO_ENV", environment)

    with pytest.raises(CommandError, match="desenvolvimento"):
        call_command("seed_demo")

    assert not Clinic.infrastructure_objects.filter(
        slug="clinica-demonstracao"
    ).exists()
    assert not User.objects.filter(email__endswith="@example.test").exists()


@pytest.mark.parametrize(
    ("debug", "allowed"),
    ((False, True), (True, False), (False, False)),
)
def test_seed_demo_requires_debug_and_explicit_safe_setting_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    debug: bool,
    allowed: bool,
) -> None:
    """Development alone is insufficient without both local safety gates."""
    monkeypatch.setenv("DJANGO_ENV", "development")
    monkeypatch.setattr(settings, "DEBUG", debug)
    monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", allowed, raising=False)

    with pytest.raises(CommandError, match="habilitado"):
        call_command("seed_demo")

    assert not Clinic.infrastructure_objects.filter(
        slug="clinica-demonstracao"
    ).exists()
    assert not User.objects.filter(email__endswith="@example.test").exists()


@pytest.mark.parametrize(
    "changes",
    (
        {"password": "usable-secret"},
        {"email": "different@example.test"},
        {"first_name": "Outra"},
        {"last_name": "Pessoa"},
    ),
)
def test_seed_demo_aborts_atomically_on_reserved_username_collision(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, str],
) -> None:
    """A reserved username collision never mutates credentials or memberships."""
    enable_demo_seed(monkeypatch)
    values = {
        "username": "terapeuta-demo",
        "email": "terapeuta.demo@example.test",
        "first_name": "Terapeuta",
        "last_name": "Demonstração",
    }
    password = changes.pop("password", None)
    values.update(changes)
    user = User.objects.create_user(**values, password=password)
    original_password = user.password

    with pytest.raises(CommandError, match="reservad"):
        call_command("seed_demo")

    user.refresh_from_db()
    assert user.password == original_password
    assert not Clinic.infrastructure_objects.filter(
        slug="clinica-demonstracao"
    ).exists()
    assert not ClinicMembership.infrastructure_objects.filter(user=user).exists()
    assert User.objects.count() == 1


def test_seed_demo_aborts_atomically_on_reserved_email_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reserved email attached to another identity blocks the whole seed."""
    enable_demo_seed(monkeypatch)
    user = User.objects.create_user(
        username="real-user",
        email="admin.demo@example.test",
        password="usable-secret",
    )
    original_password = user.password

    with pytest.raises(CommandError, match="reservad"):
        call_command("seed_demo")

    user.refresh_from_db()
    assert user.password == original_password
    assert not Clinic.infrastructure_objects.filter(
        slug="clinica-demonstracao"
    ).exists()
    assert not ClinicMembership.infrastructure_objects.exists()


def test_seed_demo_rejects_unproven_preexisting_unusable_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact but unproven identity is not treated as a prior demo seed."""
    enable_demo_seed(monkeypatch)
    user = User.objects.create_user(
        username="admin-demo",
        email="admin.demo@example.test",
        first_name="Administradora",
        last_name="Demonstração",
    )
    user.set_unusable_password()
    user.save(update_fields=("password",))
    original_password = user.password

    with pytest.raises(CommandError, match="reservad"):
        call_command("seed_demo")

    user.refresh_from_db()
    assert user.password == original_password
    assert not Clinic.infrastructure_objects.filter(
        slug="clinica-demonstracao"
    ).exists()
    assert not ClinicMembership.infrastructure_objects.filter(user=user).exists()


def test_model_state_has_no_missing_migrations() -> None:
    """Checked-in migrations describe the complete current model state."""
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
