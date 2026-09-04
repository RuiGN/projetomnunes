"""Tests for retention policies, legal hold and secure disposal (PRD 8.18.4)."""

from typing import Any
from uuid import uuid4

import pytest

from clinics.models import Clinic, ClinicMembership
from medical_records.contracts import (
    DEFAULT_CLINICAL_RETENTION_YEARS,
    DisposalBatchStatus,
    LegalBaseRetention,
    RetentionTrigger,
)
from medical_records.retention_models import (
    LegalHoldItem,
)
from medical_records.retention_services import (
    approve_disposal_batch,
    create_disposal_batch,
    create_retention_policy,
    execute_disposal_batch,
    institute_legal_hold,
    release_legal_hold,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Retenção")


@pytest.fixture
def admin_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="admin_ret@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.fixture
def other_admin(clinic: Clinic) -> Any:
    user = UserFactory.create(email="admin2_ret@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


def test_create_retention_policy_defaults_to_cfm_20_years(
    clinic: Clinic, admin_user: Any
) -> None:
    policy = create_retention_policy(
        clinic_id=clinic.id,
        name="Prontuário Clínico Padrão",
        resource_category="MedicalRecordEntry",
        created_by_user=admin_user,
    )
    assert policy.retention_years == DEFAULT_CLINICAL_RETENTION_YEARS
    assert policy.legal_base == LegalBaseRetention.CFM_RES_1821_2007.value
    assert policy.is_active is True
    assert policy.retention_trigger == RetentionTrigger.EPISODE_END_DATE.value


def test_institute_legal_hold_blocks_resources(
    clinic: Clinic, admin_user: Any
) -> None:
    resource_id_1 = uuid4()
    resource_id_2 = uuid4()
    hold = institute_legal_hold(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        hold_reference="PROC-2026-001",
        reason="Processo judicial em andamento",
        scope_description="Prontuários do paciente X relacionados ao caso.",
        resource_pairs=[
            ("MedicalRecordEntry", resource_id_1),
            ("ClinicalDocument", resource_id_2),
        ],
    )
    assert hold.is_active is True
    assert hold.hold_reference == "PROC-2026-001"

    items = list(LegalHoldItem.infrastructure_objects.filter(hold=hold))
    assert len(items) == 2
    item_resource_ids = {item.resource_id for item in items}
    assert resource_id_1 in item_resource_ids
    assert resource_id_2 in item_resource_ids


def test_release_legal_hold(clinic: Clinic, admin_user: Any, other_admin: Any) -> None:
    hold = institute_legal_hold(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        hold_reference="PROC-2026-002",
        reason="Investigação interna",
        scope_description="Documentos administrativos",
        resource_pairs=[],
    )
    released = release_legal_hold(
        hold=hold,
        releasing_user=other_admin,
        release_reason="Investigação encerrada sem pendências.",
    )
    assert released.is_active is False
    assert released.released_at is not None
    assert "encerrada" in released.release_reason


def test_dual_approval_requester_cannot_approve_own_batch(
    clinic: Clinic, admin_user: Any
) -> None:
    resource_id = uuid4()
    batch = create_disposal_batch(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        batch_reference="BATCH-2026-001",
        disposal_action="secure_destruction",
        justification="Prazo CFM expirado.",
        resource_pairs=[("MedicalRecordEntry", resource_id)],
    )
    # Requester attempting self-approval must be denied (segregation of duties)
    with pytest.raises(PermissionError, match="requester"):
        approve_disposal_batch(batch=batch, approving_user=admin_user)


def test_disposal_batch_with_legal_hold_blocked(
    clinic: Clinic, admin_user: Any, other_admin: Any
) -> None:
    resource_id = uuid4()
    # Institute a legal hold on the resource
    institute_legal_hold(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        hold_reference="HOLD-2026-003",
        reason="Bloqueio pré-descarte",
        scope_description="Prontuário em análise.",
        resource_pairs=[("MedicalRecordEntry", resource_id)],
    )
    batch = create_disposal_batch(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        batch_reference="BATCH-2026-002",
        disposal_action="secure_destruction",
        justification="Tentativa de descarte com hold ativo",
        resource_pairs=[("MedicalRecordEntry", resource_id)],
    )
    with pytest.raises(ValueError, match="legal hold"):
        approve_disposal_batch(batch=batch, approving_user=other_admin)


def test_complete_disposal_flow_issues_certificate(
    clinic: Clinic, admin_user: Any, other_admin: Any
) -> None:
    resource_id = uuid4()
    batch = create_disposal_batch(
        clinic_id=clinic.id,
        requesting_user=admin_user,
        batch_reference="BATCH-2026-OK",
        disposal_action="secure_destruction",
        justification="Prazo CFM expirado, sem hold ativo.",
        resource_pairs=[("MedicalRecordEntry", resource_id)],
    )
    approve_disposal_batch(batch=batch, approving_user=other_admin)
    certificate = execute_disposal_batch(batch=batch, executing_user=other_admin)

    assert certificate.items_hash != ""
    assert "Certificate of Disposal" in certificate.certificate_text
    # Certificate must NOT contain clinical content
    assert "paciente" not in certificate.certificate_text.lower()

    batch.refresh_from_db()
    assert batch.status == DisposalBatchStatus.COMPLETED.value
    assert batch.items_processed == 1
