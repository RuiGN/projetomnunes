"""Patient-resource authorization acceptance tests for PRD 8.4.3."""

from __future__ import annotations

import importlib.util
from datetime import date

import pytest

import people.policies
import people.selectors
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from people import models as people_models
from people.models import CareRelationship
from people.policies import PatientAuthorizationPolicy
from people.selectors import patient_visible_to

pytestmark = pytest.mark.django_db


def test_patient_authorization_policy_is_available() -> None:
    assert hasattr(people.policies, "PatientAuthorizationPolicy")


def test_care_relationship_persistence_is_available() -> None:
    assert importlib.util.find_spec("people.models") is not None


def test_care_relationship_model_is_available() -> None:
    assert hasattr(people_models, "CareRelationship")


def test_patient_authorization_policy_exposes_a_decision_method() -> None:
    assert hasattr(people.policies.PatientAuthorizationPolicy, "is_allowed")


def test_patient_selector_is_available() -> None:
    assert hasattr(people.selectors, "patient_visible_to")


def create_clinic_user(*, clinic: Clinic, role: str, local_part: str) -> User:
    user = User.objects.create_user(email=f"{local_part}@example.test")
    ClinicMembership.infrastructure_objects.create(
        clinic=clinic,
        user=user,
        role=role,
        valid_from=date.today(),
    )
    return user


def test_clinical_access_requires_active_therapist_patient_relationship() -> None:
    clinic = Clinic.infrastructure_objects.create(name="Clinical", slug="clinical")
    therapist = create_clinic_user(
        clinic=clinic, role="therapist", local_part="linked-therapist"
    )
    patient = create_clinic_user(
        clinic=clinic, role="patient", local_part="linked-patient"
    )
    policy = PatientAuthorizationPolicy()

    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=patient,
            action="patient.clinical.read",
            record_is_active=True,
        )
        is False
    )

    relationship = CareRelationship.infrastructure_objects.create(
        clinic=clinic,
        therapist=therapist,
        patient=patient,
        valid_from=date.today(),
    )
    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=patient,
            action="patient.clinical.read",
            record_is_active=True,
        )
        is True
    )

    relationship.is_active = False
    relationship.save(update_fields=("is_active", "updated_at"))
    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=patient,
            action="patient.clinical.read",
            record_is_active=True,
        )
        is False
    )


def test_resource_state_and_patient_tenant_are_mandatory() -> None:
    clinic = Clinic.infrastructure_objects.create(name="Clinic A", slug="patient-a")
    other_clinic = Clinic.infrastructure_objects.create(
        name="Clinic B", slug="patient-b"
    )
    therapist = create_clinic_user(
        clinic=clinic, role="therapist", local_part="tenant-therapist"
    )
    foreign_patient = create_clinic_user(
        clinic=other_clinic, role="patient", local_part="foreign-patient"
    )
    CareRelationship.infrastructure_objects.create(
        clinic=clinic,
        therapist=therapist,
        patient=foreign_patient,
        valid_from=date.today(),
    )
    policy = PatientAuthorizationPolicy()

    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=foreign_patient,
            action="patient.clinical.read",
            record_is_active=True,
        )
        is False
    )

    local_patient = create_clinic_user(
        clinic=clinic, role="patient", local_part="inactive-record-patient"
    )
    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=local_patient,
            action="patient.demographics.read",
            record_is_active=False,
        )
        is False
    )

    local_patient.is_active = False
    local_patient.save(update_fields=("is_active",))
    assert (
        policy.is_allowed(
            actor=therapist,
            clinic=clinic,
            patient=local_patient,
            action="patient.demographics.read",
            record_is_active=True,
        )
        is False
    )
    assert (
        patient_visible_to(
            actor=therapist,
            clinic=clinic,
            patient_id=local_patient.pk,
            action="patient.demographics.read",
        )
        is None
    )


def test_administrative_staff_can_read_demographics_but_not_clinical_data() -> None:
    clinic = Clinic.infrastructure_objects.create(name="Reception", slug="reception")
    staff = create_clinic_user(
        clinic=clinic,
        role="administrative_staff",
        local_part="administrative-staff",
    )
    patient = create_clinic_user(
        clinic=clinic, role="patient", local_part="reception-patient"
    )
    policy = PatientAuthorizationPolicy()

    assert (
        policy.is_allowed(
            actor=staff,
            clinic=clinic,
            patient=patient,
            action="patient.demographics.read",
            record_is_active=True,
        )
        is True
    )
    assert (
        policy.is_allowed(
            actor=staff,
            clinic=clinic,
            patient=patient,
            action="patient.clinical.read",
            record_is_active=True,
        )
        is False
    )


def test_patient_selector_denies_unlinked_and_cross_tenant_identifiers() -> None:
    clinic = Clinic.infrastructure_objects.create(name="Selector A", slug="selector-a")
    other_clinic = Clinic.infrastructure_objects.create(
        name="Selector B", slug="selector-b"
    )
    therapist = create_clinic_user(
        clinic=clinic, role="therapist", local_part="selector-therapist"
    )
    linked_patient = create_clinic_user(
        clinic=clinic, role="patient", local_part="selector-linked"
    )
    unlinked_patient = create_clinic_user(
        clinic=clinic, role="patient", local_part="selector-unlinked"
    )
    foreign_patient = create_clinic_user(
        clinic=other_clinic, role="patient", local_part="selector-foreign"
    )
    CareRelationship.infrastructure_objects.create(
        clinic=clinic,
        therapist=therapist,
        patient=linked_patient,
        valid_from=date.today(),
    )

    assert (
        patient_visible_to(
            actor=therapist,
            clinic=clinic,
            patient_id=linked_patient.pk,
            action="patient.clinical.read",
        )
        == linked_patient
    )
    assert (
        patient_visible_to(
            actor=therapist,
            clinic=clinic,
            patient_id=unlinked_patient.pk,
            action="patient.clinical.read",
        )
        is None
    )
    assert (
        patient_visible_to(
            actor=therapist,
            clinic=clinic,
            patient_id=foreign_patient.pk,
            action="patient.clinical.read",
        )
        is None
    )
