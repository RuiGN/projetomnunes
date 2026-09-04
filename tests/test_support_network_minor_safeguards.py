"""Tests for minor safeguards and legal guardian representation (8.16.2)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from support_network.contracts import AgeTier, GuardianVerificationStatus
from support_network.guardian_services import (
    dispute_legal_guardian_consent,
    evaluate_and_apply_minor_guardrail,
    register_legal_guardian_consent,
    revoke_legal_guardian_consent,
    transition_minor_to_adult,
    verify_legal_guardian_consent,
)
from support_network.models import MinorProfileGuardrail
from support_network.policies import can_manage_minor_guardian
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Menor")


@pytest.fixture
def staff_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="profissional@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def guardian_user(clinic_fixture: Clinic) -> Any:
    return UserFactory.create(email="responsavel@exemplo.com")


@pytest.fixture
def minor_patient_profile(db: Any, clinic_fixture: Clinic) -> PatientProfile:
    user = UserFactory.create(email="menor@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic_fixture,
        user=user,
        full_name="Menor Paciente",
        birth_date="2012-05-10",
    )


@pytest.mark.django_db
def test_evaluate_minor_age_tiers_and_guardrails(
    clinic_fixture: Clinic,
    minor_patient_profile: PatientProfile,
) -> None:
    # Child (< 12)
    child_guard = evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=10,
    )
    assert child_guard.age_tier == AgeTier.CHILD.value
    assert child_guard.is_minor is True
    assert child_guard.directory_search_allowed is False
    assert child_guard.open_messaging_allowed is False
    assert child_guard.export_requires_guardian_approval is True

    # Young teen (12-15)
    teen_guard = evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=14,
    )
    assert teen_guard.age_tier == AgeTier.YOUNG_TEEN.value
    assert teen_guard.is_minor is True
    assert teen_guard.directory_search_allowed is False
    assert teen_guard.open_messaging_allowed is False

    # Older teen (16-17)
    older_teen_guard = evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=17,
    )
    assert older_teen_guard.age_tier == AgeTier.OLDER_TEEN.value
    assert older_teen_guard.is_minor is True

    # Adult (>= 18)
    adult_guard = evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=18,
    )
    assert adult_guard.age_tier == AgeTier.ADULT.value
    assert adult_guard.is_minor is False
    assert adult_guard.directory_search_allowed is True
    assert adult_guard.open_messaging_allowed is True
    assert adult_guard.export_requires_guardian_approval is False


@pytest.mark.django_db
def test_emancipated_minor_is_treated_as_adult(
    clinic_fixture: Clinic,
    minor_patient_profile: PatientProfile,
) -> None:
    guard = evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=16,
        is_emancipated=True,
    )
    assert guard.age_tier == AgeTier.ADULT.value
    assert guard.is_minor is False
    assert guard.is_emancipated is True
    assert guard.directory_search_allowed is True


@pytest.mark.django_db
def test_guardian_consent_lifecycle_verification_and_dispute(
    clinic_fixture: Clinic,
    minor_patient_profile: PatientProfile,
    guardian_user: Any,
    staff_user: Any,
) -> None:
    # Setup initial guardrail as minor
    evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=13,
    )

    # Register consent
    consent = register_legal_guardian_consent(
        clinic_id=clinic_fixture.id,
        minor_patient_id=minor_patient_profile.id,
        guardian_name="Maria Responsável",
        guardian_email=guardian_user.email,
        guardian_phone="+5511999999999",
        document_type="CERTIDAO_NASCIMENTO",
        document_raw_id="1234567890",
        guardian_user=guardian_user,
    )
    assert consent.verification_status == GuardianVerificationStatus.PENDING.value
    # Assert document ID is pseudonymized/hashed and not saved in plaintext
    assert consent.document_hash != "1234567890"
    assert len(consent.document_hash) == 64  # SHA-256

    # Verify consent
    verified = verify_legal_guardian_consent(
        clinic_id=clinic_fixture.id,
        consent_id=consent.id,
        verified_by=staff_user,
    )
    assert verified.verification_status == GuardianVerificationStatus.VERIFIED.value
    assert verified.is_valid() is True

    guardrail = MinorProfileGuardrail.objects.for_clinic(clinic_fixture.id).get(
        patient_id=minor_patient_profile.id
    )
    assert guardrail.guardian_consent_verified is True

    # Policy check: guardian now has authorization to manage minor settings
    assert can_manage_minor_guardian(
        user=guardian_user,
        clinic_id=clinic_fixture.id,
        minor_patient_id=minor_patient_profile.id,
    )

    # Dispute consent (e.g. conflicting custody documentation)
    disputed = dispute_legal_guardian_consent(
        clinic_id=clinic_fixture.id,
        consent_id=consent.id,
        dispute_reason="Impugnação de guarda apresentada por outro genitor.",
    )
    assert disputed.verification_status == GuardianVerificationStatus.DISPUTED.value
    assert disputed.is_valid() is False

    guardrail.refresh_from_db()
    assert guardrail.guardian_consent_verified is False

    # Revoke consent
    revoked = revoke_legal_guardian_consent(
        clinic_id=clinic_fixture.id,
        consent_id=consent.id,
        revoked_by=staff_user,
    )
    assert revoked.verification_status == GuardianVerificationStatus.REVOKED.value
    assert revoked.is_valid() is False


@pytest.mark.django_db
def test_transition_minor_to_adult_milestone(
    clinic_fixture: Clinic,
    minor_patient_profile: PatientProfile,
) -> None:
    evaluate_and_apply_minor_guardrail(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
        age=17,
    )

    adult_guard = transition_minor_to_adult(
        clinic_id=clinic_fixture.id,
        patient_profile_id=minor_patient_profile.id,
    )
    assert adult_guard.age_tier == AgeTier.ADULT.value
    assert adult_guard.is_minor is False
    assert adult_guard.directory_search_allowed is True
    assert adult_guard.open_messaging_allowed is True
    assert adult_guard.export_requires_guardian_approval is False
