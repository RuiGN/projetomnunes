"""Models for electronic signatures, challenge tokens and custody chain (8.18.3)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from medical_records.contracts import (
    SignatureLevel,
    SignatureStatus,
    SignatureType,
    SignerRole,
)
from medical_records.entry_models import (
    InfrastructureMedicalRecordsManager,
    MedicalRecordsTenantManager,
)


class SignatureChallenge(UUIDTimestampedModel):
    """Single-use authentication challenge for electronic signature (8.18.3)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="signature_challenges",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="signature_challenges",
    )
    challenge_token = models.CharField(max_length=128)  # One-time token
    expires_at = models.DateTimeField()
    is_consumed = models.BooleanField(default=False)
    consumed_at = models.DateTimeField(null=True, blank=True)
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = MedicalRecordsTenantManager["SignatureChallenge"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "SignatureChallenge"
    ]()

    class Meta:
        db_table = "medical_records_signature_challenges"
        indexes = [
            models.Index(fields=["clinic", "user", "is_consumed"]),
        ]

    def __str__(self) -> str:
        return f"Challenge for user {self.user_id} (consumed={self.is_consumed})"


class ElectronicSignature(UUIDTimestampedModel):
    """Cryptographic evidence of an electronic signature with custody chain (8.18.3)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="electronic_signatures",
    )
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="electronic_signatures",
    )
    resource_type = models.CharField(max_length=64)  # e.g. "MedicalRecordEntry"
    resource_id = models.UUIDField()
    resource_version = models.IntegerField(default=1)
    signature_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.name) for t in SignatureType],
        default=SignatureType.CLINICAL_SIGNOFF.value,
    )
    signer_role = models.CharField(
        max_length=32,
        choices=[(r.value, r.name) for r in SignerRole],
        default=SignerRole.THERAPIST.value,
    )
    signature_level = models.CharField(
        max_length=32,
        choices=[(sl.value, sl.name) for sl in SignatureLevel],
        default=SignatureLevel.SIMPLE.value,
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in SignatureStatus],
        default=SignatureStatus.VALID.value,
    )
    # Cryptographic evidence
    content_hash = models.CharField(max_length=64)  # SHA-256 of signed content
    signature_value = models.TextField(blank=True, default="")
    algorithm = models.CharField(max_length=32, default="SHA-256")
    certificate_reference = models.TextField(blank=True, default="")
    signed_at = models.DateTimeField(default=timezone.now)
    # Probative manifest
    manifest = models.JSONField(default=dict)  # IP, timestamp, context, provider info
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # Revocation
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_signatures",
    )
    revocation_reason = models.TextField(blank=True, default="")

    objects = MedicalRecordsTenantManager["ElectronicSignature"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "ElectronicSignature"
    ]()

    class Meta:
        db_table = "medical_records_electronic_signatures"
        indexes = [
            models.Index(fields=["clinic", "resource_type", "resource_id"]),
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["content_hash"]),
        ]

    def __str__(self) -> str:
        return (
            f"Signature {self.signature_type} on {self.resource_type}"
            f" {self.resource_id} ({self.status})"
        )
