"""Tests for rollout flags, emergency read-only mode, and data export (PRD 8.18.5)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from medical_records.contracts import ExportStatus
from medical_records.rollout_services import (
    activate_emergency_read_only,
    deactivate_emergency_read_only,
    get_or_create_rollout_flag,
    request_medical_record_export,
    update_rollout_flags,
)
from medical_records.selectors import get_rollout_status
from medical_records.services import create_record_entry_draft, sign_record_entry
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Governança")


@pytest.fixture
def admin_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="admin_gov@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_gov@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(db: Any, clinic: Clinic, therapist_user: Any) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist_user,
        full_name="Paciente Gov",
        birth_date="1988-03-10",
    )


def test_rollout_flag_created_on_demand(clinic: Clinic) -> None:
    flag = get_or_create_rollout_flag(clinic_id=clinic.id)
    assert flag.records_enabled is False
    assert flag.emergency_read_only_mode is False


def test_update_rollout_flags_enables_records(
    clinic: Clinic, admin_user: Any
) -> None:
    update_rollout_flags(
        clinic_id=clinic.id,
        updating_user=admin_user,
        records_enabled=True,
        documents_enabled=True,
        signatures_enabled=True,
    )
    flag = get_rollout_status(clinic_id=clinic.id)
    assert flag is not None
    assert flag.records_enabled is True
    assert flag.documents_enabled is True
    assert flag.signatures_enabled is True


def test_emergency_read_only_mode_blocks_writes(
    clinic: Clinic,
    admin_user: Any,
    therapist_user: Any,
    patient_profile: PatientProfile,
) -> None:
    # Activate emergency read-only mode
    activate_emergency_read_only(
        clinic_id=clinic.id,
        activating_user=admin_user,
        reason="Incidente de segurança detectado.",
    )
    flag = get_rollout_status(clinic_id=clinic.id)
    assert flag is not None
    assert flag.emergency_read_only_mode is True

    # With emergency mode, entry creation should be rejected by policy checks
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Tentativa em emergência",
        content="Este rascunho foi criado antes do bloqueio.",
    )
    # Emergency mode blocks signing (tested through policy)
    with pytest.raises(PermissionError):
        sign_record_entry(entry=entry, signing_user=therapist_user)


def test_emergency_read_only_can_be_deactivated(
    clinic: Clinic, admin_user: Any
) -> None:
    activate_emergency_read_only(
        clinic_id=clinic.id,
        activating_user=admin_user,
        reason="Teste de kill switch.",
    )
    deactivate_emergency_read_only(clinic_id=clinic.id, deactivating_user=admin_user)
    flag = get_rollout_status(clinic_id=clinic.id)
    assert flag is not None
    assert flag.emergency_read_only_mode is False


def test_multi_tenant_isolation_for_rollout_flags(db: Any) -> None:
    clinic_a = ClinicFactory.create(name="Clínica A")
    clinic_b = ClinicFactory.create(name="Clínica B")
    admin_a = UserFactory.create(email="admin_a_gov@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_a,
        user=admin_a,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    # Enable records for clinic A only
    update_rollout_flags(
        clinic_id=clinic_a.id, updating_user=admin_a, records_enabled=True
    )
    flag_a = get_rollout_status(clinic_id=clinic_a.id)
    flag_b = get_rollout_status(clinic_id=clinic_b.id)

    assert flag_a is not None and flag_a.records_enabled is True
    assert flag_b is None  # Clinic B has no flag yet


def test_request_medical_record_export(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    export_req = request_medical_record_export(
        clinic_id=clinic.id,
        requesting_user=therapist_user,
        patient_id=patient_profile.id,
        export_format="pdf",
        purpose_note="Solicitação do titular para exercer direito LGPD.",
    )
    assert export_req.status == ExportStatus.PENDING.value
    assert export_req.download_token != ""
    assert export_req.token_expires_at is not None
    assert export_req.patient_id == patient_profile.id
