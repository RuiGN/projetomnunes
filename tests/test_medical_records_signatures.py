"""Tests for electronic signatures, challenges and integrity verification (PRD 8.18)."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from clinics.models import Clinic, ClinicMembership
from medical_records.contracts import SignatureStatus, SignatureType, SignerRole
from medical_records.selectors import verify_signature_integrity
from medical_records.signature_services import (
    apply_electronic_signature,
    issue_signature_challenge,
    revoke_signature,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Assinaturas")


@pytest.fixture
def therapist_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_sig@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def other_admin(clinic: Clinic) -> Any:
    user = UserFactory.create(email="admin_sig@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


def test_issue_and_consume_challenge(clinic: Clinic, therapist_user: Any) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
        ip_address="10.0.0.1",
    )
    assert challenge.is_consumed is False
    assert challenge.challenge_token != ""
    assert challenge.resource_id == resource_id


def test_apply_signature_with_valid_challenge(
    clinic: Clinic, therapist_user: Any
) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    content = "Final clinical note content for signing."
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    signature = apply_electronic_signature(
        clinic_id=clinic.id,
        signer_user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
        content=content,
        challenge_token=challenge.challenge_token,
        signature_type=SignatureType.CLINICAL_SIGNOFF.value,
        signer_role=SignerRole.THERAPIST.value,
        ip_address="10.0.0.1",
    )
    assert signature.status == SignatureStatus.VALID.value
    assert signature.content_hash != ""
    assert signature.manifest["resource_type"] == "MedicalRecordEntry"
    assert signature.manifest["content_hash"] == signature.content_hash

    # Challenge should be consumed
    challenge.refresh_from_db()
    assert challenge.is_consumed is True


def test_signature_fails_with_invalid_challenge_token(
    clinic: Clinic, therapist_user: Any
) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    with pytest.raises(ValueError, match="Invalid or missing signature challenge"):
        apply_electronic_signature(
            clinic_id=clinic.id,
            signer_user=therapist_user,
            resource_type="MedicalRecordEntry",
            resource_id=resource_id,
            content="Some content",
            challenge_token="invalid-token-99999",
        )


def test_expired_challenge_is_rejected(clinic: Clinic, therapist_user: Any) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    # Force expiry
    challenge.expires_at = timezone.now() - timedelta(minutes=1)
    challenge.save(update_fields=["expires_at"])

    with pytest.raises(ValueError, match="expired"):
        apply_electronic_signature(
            clinic_id=clinic.id,
            signer_user=therapist_user,
            resource_type="MedicalRecordEntry",
            resource_id=resource_id,
            content="Content",
            challenge_token=challenge.challenge_token,
        )


def test_verify_signature_integrity_valid(
    clinic: Clinic, therapist_user: Any
) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    content = "Clinical content to verify."
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    apply_electronic_signature(
        clinic_id=clinic.id,
        signer_user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
        content=content,
        challenge_token=challenge.challenge_token,
    )
    result = verify_signature_integrity(
        clinic_id=clinic.id,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    assert result["status"] == SignatureStatus.VALID.value
    assert result["content_hash"] != ""


def test_verify_signature_not_signed_returns_not_signed_status(
    clinic: Clinic, therapist_user: Any
) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    result = verify_signature_integrity(
        clinic_id=clinic.id,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    assert result["status"] == "not_signed"
    assert result["signature"] is None


def test_revoke_signature_records_reason(clinic: Clinic, therapist_user: Any) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    signature = apply_electronic_signature(
        clinic_id=clinic.id,
        signer_user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
        content="Content to revoke.",
        challenge_token=challenge.challenge_token,
    )
    revoked = revoke_signature(
        signature=signature,
        revoking_user=therapist_user,
        reason="Assinatura aplicada em documento errado.",
    )
    assert revoked.status == SignatureStatus.REVOKED.value
    assert revoked.revoked_at is not None
    assert "documento errado" in revoked.revocation_reason


def test_cannot_revoke_already_revoked_signature(
    clinic: Clinic, therapist_user: Any
) -> None:
    from uuid import uuid4

    resource_id = uuid4()
    challenge = issue_signature_challenge(
        clinic_id=clinic.id,
        user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
    )
    signature = apply_electronic_signature(
        clinic_id=clinic.id,
        signer_user=therapist_user,
        resource_type="MedicalRecordEntry",
        resource_id=resource_id,
        content="Revoke twice.",
        challenge_token=challenge.challenge_token,
    )
    revoke_signature(
        signature=signature, revoking_user=therapist_user, reason="First revocation."
    )
    with pytest.raises(ValueError, match="Cannot revoke"):
        revoke_signature(
            signature=signature,
            revoking_user=therapist_user,
            reason="Second revocation.",
        )
