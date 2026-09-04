"""Models for tenant rollout control, audit metrics and export requests (8.18.5)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from medical_records.contracts import (
    ExportFormat,
    ExportStatus,
)
from medical_records.entry_models import (
    InfrastructureMedicalRecordsManager,
    MedicalRecordsTenantManager,
)


class MedicalRecordsRolloutFlag(UUIDTimestampedModel):
    """Per-tenant feature flag controlling medical records functionality (8.18.5)."""

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medical_records_rollout_flag",
    )
    records_enabled = models.BooleanField(default=False)
    documents_enabled = models.BooleanField(default=False)
    signatures_enabled = models.BooleanField(default=False)
    retention_enforcement_enabled = models.BooleanField(default=False)
    export_enabled = models.BooleanField(default=False)
    # Emergency kill switch — forces read-only mode across the tenant
    emergency_read_only_mode = models.BooleanField(default=False)
    emergency_activated_at = models.DateTimeField(null=True, blank=True)
    emergency_activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_medical_records_emergencies",
    )
    emergency_reason = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_medical_records_flags",
    )

    objects = MedicalRecordsTenantManager["MedicalRecordsRolloutFlag"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "MedicalRecordsRolloutFlag"
    ]()

    class Meta:
        db_table = "medical_records_rollout_flags"

    def __str__(self) -> str:
        return (
            f"MedicalRecordsRollout clinic={self.clinic_id} "
            f"(read_only={self.emergency_read_only_mode})"
        )


class MedicalRecordsAuditMetric(UUIDTimestampedModel):
    """Daily compliance metrics aggregated without clinical text (8.18.5)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medical_records_audit_metrics",
    )
    date = models.DateField(default=timezone.now)
    entries_created = models.IntegerField(default=0)
    entries_signed = models.IntegerField(default=0)
    addenda_created = models.IntegerField(default=0)
    documents_uploaded = models.IntegerField(default=0)
    documents_rejected = models.IntegerField(default=0)
    signatures_applied = models.IntegerField(default=0)
    signatures_revoked = models.IntegerField(default=0)
    access_logs_count = models.IntegerField(default=0)
    exports_requested = models.IntegerField(default=0)
    disposal_items_processed = models.IntegerField(default=0)
    integrity_failures = models.IntegerField(default=0)
    signature_failures = models.IntegerField(default=0)
    quarantine_backlog = models.IntegerField(default=0)

    objects = MedicalRecordsTenantManager["MedicalRecordsAuditMetric"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "MedicalRecordsAuditMetric"
    ]()

    class Meta:
        db_table = "medical_records_audit_metrics"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "date"],
                name="unique_medical_records_metric_date",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "date"]),
        ]

    def __str__(self) -> str:
        return f"MedicalRecordsMetric clinic={self.clinic_id} on {self.date}"


class MedicalRecordExportRequest(UUIDTimestampedModel):
    """Data subject export request for their full medical record (8.18.5)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medical_record_export_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="medical_record_export_requests",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="record_export_requests",
    )
    export_format = models.CharField(
        max_length=32,
        choices=[(f.value, f.name) for f in ExportFormat],
        default=ExportFormat.PDF.value,
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in ExportStatus],
        default=ExportStatus.PENDING.value,
    )
    purpose_note = models.TextField(blank=True, default="")
    download_token = models.CharField(max_length=128, blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    download_count = models.IntegerField(default=0)
    max_downloads = models.IntegerField(default=3)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    file_path = models.CharField(max_length=512, blank=True, default="")

    objects = MedicalRecordsTenantManager["MedicalRecordExportRequest"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "MedicalRecordExportRequest"
    ]()

    class Meta:
        db_table = "medical_records_export_requests"
        indexes = [
            models.Index(fields=["clinic", "patient", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"ExportRequest {self.export_format} "
            f"for patient {self.patient_id} ({self.status})"
        )
