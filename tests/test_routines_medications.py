"""Tests for safe, non-prescriptive medication tracking and adherence (8.14.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from routines import medication_services, policies, selectors
from routines.models import (
    MedicationAdministrationRoute,
    MedicationLogStatus,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Medicamentos Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.med@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="terapeuta.med@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(test_clinic: Clinic, patient_user: User) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Medicamento Seguro",
        birth_date=date(1985, 4, 12),
    )


@pytest.mark.django_db
def test_register_prescribed_medication_reproduces_external_prescription(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Medication registration requires external prescriber details."""
    med = medication_services.register_prescribed_medication(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        medication_name="Sertralina",
        presentation="Comprimido",
        prescribed_dose="50 mg",
        route=MedicationAdministrationRoute.ORAL,
        schedule_times=["08:00"],
        start_date=date(2026, 9, 1),
        prescriber_name="Dra. Ana Silva",
        prescriber_registration="CRM-SP 123456",
        prescription_date=date(2026, 8, 25),
        instructions="Tomar pela manhã após o desjejum",
    )
    assert med.medication_name == "Sertralina"
    assert med.prescriber_name == "Dra. Ana Silva"
    assert med.prescriber_registration == "CRM-SP 123456"

    # Prescriber info is mandatory
    with pytest.raises(ValidationError, match="Identificação do prescritor externo"):
        medication_services.register_prescribed_medication(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            medication_name="Paracetamol",
            presentation="Comprimido",
            prescribed_dose="750 mg",
            schedule_times=["12:00"],
            start_date=date(2026, 9, 1),
            prescriber_name="",
            prescriber_registration="",
            prescription_date=date(2026, 9, 1),
        )


@pytest.mark.django_db
def test_safety_guardrail_prohibits_automated_prescriptive_advice(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Clinical guardrails block any advice to alter, double, or compensate doses."""
    with pytest.raises(ValidationError, match="Conteúdo vedado por segurança clínica"):
        medication_services.register_prescribed_medication(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            medication_name="Antidepressivo",
            presentation="Comprimido",
            prescribed_dose="20 mg",
            schedule_times=["09:00"],
            start_date=date(2026, 9, 1),
            prescriber_name="Dr. Carlos",
            prescriber_registration="CRM 9999",
            prescription_date=date(2026, 9, 1),
            instructions="Se esquecer, tome o dobro na próxima dose",
        )


@pytest.mark.django_db
def test_medication_dose_adherence_and_no_double_dosing(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Records scheduled doses without automatic compensation for missed ones."""
    med = medication_services.register_prescribed_medication(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        medication_name="Escitalopram",
        presentation="Gotas",
        prescribed_dose="10 mg",
        schedule_times=["08:00"],
        start_date=date(2026, 9, 1),
        prescriber_name="Dr. João",
        prescriber_registration="CRM 5555",
        prescription_date=date(2026, 9, 1),
    )

    t1 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    t3 = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)

    # 1: Taken on time
    medication_services.record_medication_dose(
        clinic_id=test_clinic.id,
        medication_id=med.id,
        scheduled_time=t1,
        status=MedicationLogStatus.TAKEN,
    )
    # 2: Taken with delay
    medication_services.record_medication_dose(
        clinic_id=test_clinic.id,
        medication_id=med.id,
        scheduled_time=t2,
        status=MedicationLogStatus.LATE,
    )
    # 3: Omitted (forgotten)
    medication_services.record_medication_dose(
        clinic_id=test_clinic.id,
        medication_id=med.id,
        scheduled_time=t3,
        status=MedicationLogStatus.OMITTED,
    )

    summary = selectors.medication_adherence_summary(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
    )
    assert summary["total_scheduled_doses"] == 3
    assert summary["taken"] == 1
    assert summary["late"] == 1
    assert summary["omitted"] == 1
    assert summary["adherence_rate_percent"] == 66.7


@pytest.mark.django_db
def test_medication_sharing_consent_and_audit(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    patient_user: User,
    therapist_user: User,
) -> None:
    """Clinicians cannot view medication history without explicit patient consent."""
    # Before consent
    assert not policies.can_view_medication_adherence(
        user=therapist_user,
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )

    # Grant consent
    consent = medication_services.grant_medication_share_consent(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        granted_to_user_id=therapist_user.id,
        actor_id=patient_user.id,
    )
    assert consent.is_active

    # After consent granted
    assert policies.can_view_medication_adherence(
        user=therapist_user,
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )

    # Revoke consent
    medication_services.revoke_medication_share_consent(
        clinic_id=test_clinic.id,
        consent_id=consent.id,
        actor_id=patient_user.id,
    )

    # After revocation
    assert not policies.can_view_medication_adherence(
        user=therapist_user,
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )

    # Audit events verified
    audits = AuditEvent.infrastructure_objects.filter(clinic_id=test_clinic.id)
    assert audits.filter(action="routines.medication_consent_granted").exists()
    assert audits.filter(action="routines.medication_consent_revoked").exists()
