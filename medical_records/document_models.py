"""Models for clinical documents, quarantine tracking, and access logs."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from medical_records.contracts import (
    ConfidentialityLevel,
    DocumentScanStatus,
    DocumentType,
    PurposeOfUse,
)
from medical_records.entry_models import (
    ClinicalEpisode,
    InfrastructureMedicalRecordsManager,
    MedicalRecordsTenantManager,
)


class ClinicalDocument(UUIDTimestampedModel):
    """Regulated clinical document with quarantine and virus scanning (8.18.2)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="clinical_documents",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="clinical_documents",
    )
    episode = models.ForeignKey(
        ClinicalEpisode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_documents",
    )
    document_type = models.CharField(
        max_length=32,
        choices=[(d.value, d.name) for d in DocumentType],
        default=DocumentType.MEDICAL_REPORT.value,
    )
    confidentiality_level = models.CharField(
        max_length=32,
        choices=[(c.value, c.name) for c in ConfidentialityLevel],
        default=ConfidentialityLevel.STANDARD.value,
    )
    scan_status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in DocumentScanStatus],
        default=DocumentScanStatus.QUARANTINE.value,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    file_name = models.CharField(max_length=255)
    file_size_bytes = models.BigIntegerField()
    mime_type = models.CharField(max_length=128)
    sha256_checksum = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=512)
    quarantine_reason = models.TextField(blank=True, default="")
    scanned_at = models.DateTimeField(null=True, blank=True)
    scan_clean = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_documents",
    )
    watermarked = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)

    objects = MedicalRecordsTenantManager["ClinicalDocument"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["ClinicalDocument"]()

    class Meta:
        db_table = "medical_records_clinical_documents"
        indexes = [
            models.Index(fields=["clinic", "patient", "scan_status"]),
            models.Index(fields=["clinic", "document_type"]),
            models.Index(fields=["clinic", "sha256_checksum"]),
        ]

    def __str__(self) -> str:
        return f"{self.document_type}: {self.file_name} ({self.scan_status})"


class DocumentAccessLog(UUIDTimestampedModel):
    """Audit log for access, viewing, or downloading of clinical documents (8.18.2)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="document_access_logs",
    )
    document = models.ForeignKey(
        ClinicalDocument,
        on_delete=models.CASCADE,
        related_name="access_logs",
    )
    accessor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="document_access_records",
    )
    purpose = models.CharField(
        max_length=32,
        choices=[(p.value, p.name) for p in PurposeOfUse],
        default=PurposeOfUse.CARE_DELIVERY.value,
    )
    action = models.CharField(max_length=32, default="view")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    accessed_at = models.DateTimeField(default=timezone.now)

    objects = MedicalRecordsTenantManager["DocumentAccessLog"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "DocumentAccessLog"
    ]()

    class Meta:
        db_table = "medical_records_document_access_logs"
        indexes = [
            models.Index(fields=["clinic", "document", "accessed_at"]),
        ]

    def __str__(self) -> str:
        return f"Access {self.action} on doc {self.document_id} by {self.accessor_id}"
