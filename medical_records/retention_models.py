"""Models for retention policy, legal hold, disposal batch and certificates (8.18.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from medical_records.contracts import (
    DEFAULT_CLINICAL_RETENTION_YEARS,
    DisposalAction,
    DisposalBatchStatus,
    LegalBaseRetention,
    RetentionTrigger,
)
from medical_records.entry_models import (
    InfrastructureMedicalRecordsManager,
    MedicalRecordsTenantManager,
)


class RetentionPolicy(UUIDTimestampedModel):
    """Versioned regulatory retention matrix entry (8.18.4)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="retention_policies",
    )
    name = models.CharField(max_length=255)
    resource_category = models.CharField(max_length=64)  # e.g. "MedicalRecordEntry"
    retention_years = models.IntegerField(default=DEFAULT_CLINICAL_RETENTION_YEARS)
    retention_trigger = models.CharField(
        max_length=32,
        choices=[(t.value, t.name) for t in RetentionTrigger],
        default=RetentionTrigger.EPISODE_END_DATE.value,
    )
    legal_base = models.CharField(
        max_length=32,
        choices=[(lb.value, lb.name) for lb in LegalBaseRetention],
        default=LegalBaseRetention.CFM_RES_1821_2007.value,
    )
    disposal_action = models.CharField(
        max_length=32,
        choices=[(d.value, d.name) for d in DisposalAction],
        default=DisposalAction.SECURE_DESTRUCTION.value,
    )
    applies_to_minors = models.BooleanField(default=True)
    policy_version = models.IntegerField(default=1)
    policy_owner_role = models.CharField(max_length=128, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    objects = MedicalRecordsTenantManager["RetentionPolicy"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["RetentionPolicy"]()

    class Meta:
        db_table = "medical_records_retention_policies"
        indexes = [
            models.Index(fields=["clinic", "resource_category", "is_active"]),
        ]

    def __str__(self) -> str:
        return (
            f"RetentionPolicy: {self.resource_category} "
            f"{self.retention_years}y ({self.legal_base})"
        )


class LegalHold(UUIDTimestampedModel):
    """Legal hold blocking any disposal of affected records (8.18.4)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="legal_holds",
    )
    hold_reference = models.CharField(max_length=255, unique=True)  # Case/process ref
    reason = models.TextField()
    scope_description = models.TextField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_legal_holds",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_legal_holds",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    review_due_date = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="released_legal_holds",
    )
    release_reason = models.TextField(blank=True, default="")

    objects = MedicalRecordsTenantManager["LegalHold"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["LegalHold"]()

    class Meta:
        db_table = "medical_records_legal_holds"
        indexes = [
            models.Index(fields=["clinic", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"LegalHold {self.hold_reference} (active={self.is_active})"


class LegalHoldItem(UUIDTimestampedModel):
    """Individual record item frozen by a legal hold (8.18.4)."""

    hold = models.ForeignKey(
        LegalHold,
        on_delete=models.CASCADE,
        related_name="items",
    )
    resource_type = models.CharField(max_length=64)
    resource_id = models.UUIDField()
    notes = models.TextField(blank=True, default="")

    objects = MedicalRecordsTenantManager["LegalHoldItem"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["LegalHoldItem"]()

    class Meta:
        db_table = "medical_records_legal_hold_items"
        constraints = [
            models.UniqueConstraint(
                fields=["hold", "resource_type", "resource_id"],
                name="unique_hold_resource",
            )
        ]

    def __str__(self) -> str:
        return f"HoldItem {self.resource_type}:{self.resource_id}"


class DisposalBatch(UUIDTimestampedModel):
    """Controlled dual-approval disposal batch with idempotent execution (8.18.4).

    Dual-approval invariant: approved_by must never be the same user as requested_by.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="disposal_batches",
    )
    batch_reference = models.CharField(max_length=255, unique=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_disposal_batches",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_disposal_batches",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in DisposalBatchStatus],
        default=DisposalBatchStatus.PENDING_REVIEW.value,
    )
    disposal_action = models.CharField(
        max_length=32,
        choices=[(d.value, d.name) for d in DisposalAction],
        default=DisposalAction.SECURE_DESTRUCTION.value,
    )
    justification = models.TextField()
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_log = models.TextField(blank=True, default="")
    items_count = models.IntegerField(default=0)
    items_processed = models.IntegerField(default=0)

    objects = MedicalRecordsTenantManager["DisposalBatch"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["DisposalBatch"]()

    class Meta:
        db_table = "medical_records_disposal_batches"
        indexes = [
            models.Index(fields=["clinic", "status"]),
        ]

    def __str__(self) -> str:
        return f"DisposalBatch {self.batch_reference} ({self.status})"


class DisposalItem(UUIDTimestampedModel):
    """Individual item scheduled for secure disposal (8.18.4)."""

    batch = models.ForeignKey(
        DisposalBatch,
        on_delete=models.CASCADE,
        related_name="items",
    )
    resource_type = models.CharField(max_length=64)
    resource_id = models.UUIDField()
    has_legal_hold = models.BooleanField(default=False)  # Validated before execution
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    objects = MedicalRecordsTenantManager["DisposalItem"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["DisposalItem"]()

    class Meta:
        db_table = "medical_records_disposal_items"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "resource_type", "resource_id"],
                name="unique_batch_resource",
            )
        ]

    def __str__(self) -> str:
        return f"DisposalItem {self.resource_type}:{self.resource_id}"


class DisposalCertificate(UUIDTimestampedModel):
    """Cryptographic certificate of completed disposal — no clinical data (8.18.4)."""

    batch = models.OneToOneField(
        DisposalBatch,
        on_delete=models.PROTECT,
        related_name="certificate",
    )
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_disposal_certificates",
    )
    # Proof of destruction (no clinical data)
    items_hash = models.CharField(max_length=64)  # SHA-256 of disposal item IDs
    legal_base = models.CharField(
        max_length=32,
        choices=[(lb.value, lb.name) for lb in LegalBaseRetention],
        default=LegalBaseRetention.CFM_RES_1821_2007.value,
    )
    certificate_text = models.TextField()
    is_public = models.BooleanField(default=False)

    objects = MedicalRecordsTenantManager["DisposalCertificate"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "DisposalCertificate"
    ]()

    class Meta:
        db_table = "medical_records_disposal_certificates"

    def __str__(self) -> str:
        return f"DisposalCertificate for batch {self.batch_id}"
