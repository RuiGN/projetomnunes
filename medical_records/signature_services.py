"""Services for electronic signatures and challenge-based authentication (8.18.3)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from medical_records.contracts import (
    SignatureLevel,
    SignatureStatus,
    SignatureType,
    SignerRole,
)
from medical_records.events import (
    signature_applied,
    signature_challenge_issued,
    signature_revoked,
)
from medical_records.signature_models import ElectronicSignature, SignatureChallenge

CHALLENGE_EXPIRY_MINUTES = 10


@transaction.atomic
def issue_signature_challenge(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    resource_type: str,
    resource_id: UUID,
    ip_address: str | None = None,
) -> SignatureChallenge:
    """Issue a single-use authentication challenge for electronic signing."""
    token = secrets.token_hex(32)
    expires_at = timezone.now() + timedelta(minutes=CHALLENGE_EXPIRY_MINUTES)
    challenge = SignatureChallenge.objects.create(
        clinic_id=clinic_id,
        user=cast(Any, user),
        challenge_token=token,
        expires_at=expires_at,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
    )
    signature_challenge_issued.send(sender=SignatureChallenge, challenge=challenge)
    return challenge


@transaction.atomic
def apply_electronic_signature(
    *,
    clinic_id: UUID,
    signer_user: AbstractBaseUser,
    resource_type: str,
    resource_id: UUID,
    content: str,
    challenge_token: str,
    resource_version: int = 1,
    signature_type: str = SignatureType.CLINICAL_SIGNOFF.value,
    signer_role: str = SignerRole.THERAPIST.value,
    signature_level: str = SignatureLevel.SIMPLE.value,
    ip_address: str | None = None,
    certificate_reference: str = "",
    request_id: str | None = None,
    network_origin: str = "internal",
) -> ElectronicSignature:
    """Apply an electronic signature after validating the one-time challenge."""
    # Validate challenge
    challenge = SignatureChallenge.infrastructure_objects.filter(
        clinic_id=clinic_id,
        user_id=signer_user.pk,
        challenge_token=challenge_token,
        resource_type=resource_type,
        resource_id=resource_id,
        is_consumed=False,
    ).first()
    if challenge is None:
        raise ValueError("Invalid or missing signature challenge token.")
    if timezone.now() > challenge.expires_at:
        raise ValueError("Signature challenge has expired.")
    # Consume the challenge
    challenge.is_consumed = True
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["is_consumed", "consumed_at"])

    # Compute SHA-256 hash of content being signed
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    now = timezone.now()
    manifest: dict[str, Any] = {
        "signer_id": str(signer_user.pk),
        "signer_role": signer_role,
        "signature_type": signature_type,
        "signature_level": signature_level,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "resource_version": resource_version,
        "content_hash": content_hash,
        "algorithm": "SHA-256",
        "signed_at_iso": now.isoformat(),
        "ip_address": ip_address or "",
        "certificate_reference": certificate_reference,
        "challenge_id": str(challenge.id),
    }
    signature = ElectronicSignature.objects.create(
        clinic_id=clinic_id,
        signer=cast(Any, signer_user),
        resource_type=resource_type,
        resource_id=resource_id,
        resource_version=resource_version,
        signature_type=signature_type,
        signer_role=signer_role,
        signature_level=signature_level,
        status=SignatureStatus.VALID.value,
        content_hash=content_hash,
        algorithm="SHA-256",
        certificate_reference=certificate_reference,
        signed_at=now,
        manifest=manifest,
        ip_address=ip_address,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=signer_user.pk,
        action="signature.applied",
        resource_type=resource_type,
        resource_id=str(resource_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    signature_applied.send(sender=ElectronicSignature, signature=signature)
    return signature


@transaction.atomic
def revoke_signature(
    *,
    signature: ElectronicSignature,
    revoking_user: AbstractBaseUser,
    reason: str,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> ElectronicSignature:
    """Revoke a valid signature and record the justification."""
    if signature.status != SignatureStatus.VALID.value:
        raise ValueError(
            f"Cannot revoke a signature with status '{signature.status}'."
        )
    signature.status = SignatureStatus.REVOKED.value
    signature.revoked_at = timezone.now()
    signature.revoked_by = cast(Any, revoking_user)
    signature.revocation_reason = reason
    signature.save(
        update_fields=["status", "revoked_at", "revoked_by", "revocation_reason"]
    )
    record_audit_event(
        clinic_id=signature.clinic_id,
        actor_id=revoking_user.pk,
        action="signature.revoked",
        resource_type=signature.resource_type,
        resource_id=str(signature.resource_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    signature_revoked.send(sender=ElectronicSignature, signature=signature)
    return signature
