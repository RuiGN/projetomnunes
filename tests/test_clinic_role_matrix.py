"""Acceptance tests for the clinic-scoped role and action matrix (PRD 8.4.3)."""

from datetime import date

import pytest

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from clinics.policies import ClinicAuthorizationPolicy

pytestmark = pytest.mark.django_db


ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "clinic_admin": frozenset(
        {
            "clinic.manage",
            "professionals.manage",
            "patients.create",
            "patient.demographics.read",
            "audit.read",
        }
    ),
    "therapist": frozenset(
        {
            "patient.demographics.read",
            "patient.clinical.read",
        }
    ),
    "administrative_staff": frozenset(
        {
            "patients.create",
            "patient.demographics.read",
        }
    ),
}
ALL_ACTIONS = frozenset().union(*ROLE_ACTIONS.values())


def create_actor_with_role(*, role: str) -> tuple[User, Clinic]:
    clinic = Clinic.infrastructure_objects.create(
        name=f"Clinic {role}",
        slug=f"clinic-{role.replace('_', '-')}",
    )
    actor = User.objects.create_user(email=f"{role}@example.test")
    ClinicMembership.infrastructure_objects.create(
        clinic=clinic,
        user=actor,
        role=role,
        valid_from=date.today(),
    )
    return actor, clinic


def test_initial_business_roles_include_administrative_staff() -> None:
    assert (
        "administrative_staff",
        "Equipe administrativa",
    ) in ClinicMembership.Role.choices


@pytest.mark.parametrize("role", ROLE_ACTIONS)
def test_role_action_matrix_applies_least_privilege(role: str) -> None:
    actor, clinic = create_actor_with_role(role=role)
    policy = ClinicAuthorizationPolicy()

    for action in ALL_ACTIONS:
        assert policy.is_allowed(actor, clinic, action) is (
            action in ROLE_ACTIONS[role]
        )


def test_patient_membership_has_no_staff_or_clinical_permissions() -> None:
    actor, clinic = create_actor_with_role(role="patient")
    policy = ClinicAuthorizationPolicy()

    assert all(not policy.is_allowed(actor, clinic, action) for action in ALL_ACTIONS)
