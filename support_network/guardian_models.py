"""Models for minor protections and legal guardian consent (8.16.2)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from support_network.contracts import AgeTier, GuardianVerificationStatus
from support_network.network_models import (
    InfrastructureSupportNetworkManager,
    SupportNetworkTenantManager,
)


class MinorPolicyVersion(UUIDTimestampedModel):
    """Versioned policy defining rights and safeguards for minors."""

    jurisdiction = models.CharField(max_length=10, default="BR", db_index=True)
    version = models.CharField(max_length=20, default="1.0")
    child_max_age = models.PositiveSmallIntegerField(default=11)
    young_teen_max_age = models.PositiveSmallIntegerField(default=15)
    older_teen_max_age = models.PositiveSmallIntegerField(default=17)
    requires_guardian_consent_under = models.PositiveSmallIntegerField(default=16)
    assent_required_from = models.PositiveSmallIntegerField(default=12)
    directory_search_allowed_under_18 = models.BooleanField(default=False)
    open_messaging_allowed_under_18 = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "support_network_minor_policy_versions"
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "version"],
                name="unique_jurisdiction_policy_version",
            )
        ]


class MinorProfileGuardrail(UUIDTimestampedModel):
    """Controls attached to patient profile to prevent unauthorized exposure."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="minor_guardrails",
    )
    patient = models.OneToOneField(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="minor_guardrail",
    )
    age_tier = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in AgeTier],
        default=AgeTier.ADULT.value,
        db_index=True,
    )
    is_minor = models.BooleanField(default=False, db_index=True)
    is_emancipated = models.BooleanField(default=False)
    guardian_consent_verified = models.BooleanField(default=False, db_index=True)
    directory_search_allowed = models.BooleanField(default=False)
    open_messaging_allowed = models.BooleanField(default=False)
    export_requires_guardian_approval = models.BooleanField(default=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_minor_guardrails"
        indexes = [
            models.Index(fields=["clinic", "is_minor", "guardian_consent_verified"]),
        ]


class LegalGuardianConsent(UUIDTimestampedModel):
    """Legal guardian representation record with proportional verification and audit."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="guardian_consents",
    )
    minor_patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="guardian_consents",
    )
    guardian_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guarded_patients",
    )
    guardian_name = models.CharField(max_length=255)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=50)
    document_type = models.CharField(max_length=50)  # e.g., RG, CPF, GUARDIANSHIP_ORDER
    document_hash = models.CharField(max_length=128)  # SHA-256 pseudonymized hash
    verification_status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in GuardianVerificationStatus],
        default=GuardianVerificationStatus.PENDING.value,
        db_index=True,
    )
    verification_method = models.CharField(max_length=50, default="ASSISTED_OPERATION")
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_guardian_consents",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.TextField(blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_guardian_consents",
    )

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_guardian_consents"
        indexes = [
            models.Index(fields=["clinic", "minor_patient", "verification_status"]),
            models.Index(fields=["guardian_email", "verification_status"]),
        ]

    def is_valid(self) -> bool:
        if self.verification_status != GuardianVerificationStatus.VERIFIED.value:
            return False
        if self.revoked_at is not None:
            return False
        return not (self.expires_at and timezone.now() >= self.expires_at)
