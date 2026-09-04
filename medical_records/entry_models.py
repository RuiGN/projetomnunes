"""Models for clinical episodes, medical record entries, versions and addenda."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from medical_records.contracts import (
    AddendumReason,
    EpisodeStatus,
    PurposeOfUse,
    RecordEntryStatus,
    RecordEntryType,
)

_ModelT = TypeVar("_ModelT", bound=models.Model)


class MedicalRecordsQuerySet(models.QuerySet[_ModelT]):
    """Tenant-scoped query set for medical records domain models."""

    def for_clinic(
        self: MedicalRecordsQuerySet[_ModelT], clinic_id: UUID
    ) -> MedicalRecordsQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class MedicalRecordsTenantManager(models.Manager[_ModelT]):
    """Tenant-safe default manager requiring an explicit clinic scope."""

    def get_queryset(self) -> MedicalRecordsQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return MedicalRecordsQuerySet(self.model, using=self._db)
        raise RuntimeError("Medical records queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: MedicalRecordsTenantManager[_ModelT], clinic_id: UUID
    ) -> MedicalRecordsQuerySet[_ModelT]:
        return MedicalRecordsQuerySet(self.model, using=self._db).for_clinic(clinic_id)

    def create(self, **kwargs: Any) -> _ModelT:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return super().create(**kwargs)
        clinic_id = kwargs.get("clinic_id")
        if not clinic_id and "clinic" in kwargs:
            clinic = kwargs["clinic"]
            clinic_id = getattr(clinic, "id", clinic)
        if clinic_id:
            return self.for_clinic(clinic_id).create(**kwargs)
        return MedicalRecordsQuerySet(self.model, using=self._db).create(**kwargs)


class InfrastructureMedicalRecordsManager(models.Manager[_ModelT]):
    """Unrestricted medical records access for internal tasks and audits."""

    def get_queryset(
        self: InfrastructureMedicalRecordsManager[_ModelT],
    ) -> MedicalRecordsQuerySet[_ModelT]:
        return MedicalRecordsQuerySet(self.model, using=self._db)


class ClinicalEpisode(UUIDTimestampedModel):
    """Clinical episode grouping care encounters for a patient (8.18.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="clinical_episodes",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="clinical_episodes",
    )
    attending_professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attended_episodes",
    )
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, default="")
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=[(e.value, e.name) for e in EpisodeStatus],
        default=EpisodeStatus.ACTIVE.value,
    )

    objects = MedicalRecordsTenantManager["ClinicalEpisode"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["ClinicalEpisode"]()

    class Meta:
        db_table = "medical_records_clinical_episodes"
        indexes = [
            models.Index(fields=["clinic", "patient"]),
            models.Index(fields=["clinic", "status"]),
        ]

    def __str__(self) -> str:
        return f"Episode {self.title} ({self.status})"


class MedicalRecordEntry(UUIDTimestampedModel):
    """Longitudinal medical record entry with versioning & signing (8.18.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medical_record_entries",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="medical_record_entries",
    )
    episode = models.ForeignKey(
        ClinicalEpisode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_medical_entries",
    )
    entry_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.name) for t in RecordEntryType],
        default=RecordEntryType.CLINICAL_EVOLUTION.value,
    )
    purpose_of_use = models.CharField(
        max_length=32,
        choices=[(p.value, p.name) for p in PurposeOfUse],
        default=PurposeOfUse.CARE_DELIVERY.value,
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in RecordEntryStatus],
        default=RecordEntryStatus.DRAFT.value,
    )
    current_version = models.IntegerField(default=1)
    lock_version = models.IntegerField(default=1)  # Optimistic concurrency lock
    is_administrative = models.BooleanField(default=False)
    title = models.CharField(max_length=255)
    content = models.TextField()  # Clinical narrative
    objective_data = models.JSONField(default=dict, blank=True)
    plan_and_conduct = models.TextField(blank=True, default="")
    diagnostic_hypotheses = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")  # SHA-256
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_medical_entries",
    )

    objects = MedicalRecordsTenantManager["MedicalRecordEntry"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "MedicalRecordEntry"
    ]()

    class Meta:
        db_table = "medical_records_entries"
        indexes = [
            models.Index(fields=["clinic", "patient", "status"]),
            models.Index(fields=["clinic", "entry_type"]),
            models.Index(fields=["clinic", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.entry_type}: {self.title} (v{self.current_version})"


class RecordEntryVersion(UUIDTimestampedModel):
    """Immutable version snapshot of a medical record entry (8.18.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="record_entry_versions",
    )
    entry = models.ForeignKey(
        MedicalRecordEntry,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.IntegerField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_entry_versions",
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    objective_data = models.JSONField(default=dict, blank=True)
    plan_and_conduct = models.TextField(blank=True, default="")
    diagnostic_hypotheses = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64)
    reason_for_change = models.TextField(blank=True, default="")

    objects = MedicalRecordsTenantManager["RecordEntryVersion"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager[
        "RecordEntryVersion"
    ]()

    class Meta:
        db_table = "medical_records_entry_versions"
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "version_number"],
                name="unique_entry_version_number",
            )
        ]

    def __str__(self) -> str:
        return f"Entry {self.entry_id} version {self.version_number}"


class RecordAddendum(UUIDTimestampedModel):
    """Post-signature formal addendum to prevent silent overwriting (8.18.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="record_addenda",
    )
    entry = models.ForeignKey(
        MedicalRecordEntry,
        on_delete=models.PROTECT,
        related_name="addenda",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_addenda",
    )
    addendum_number = models.IntegerField()
    reason = models.CharField(
        max_length=32,
        choices=[(r.value, r.name) for r in AddendumReason],
        default=AddendumReason.SUPPLEMENTAL_INFO.value,
    )
    content = models.TextField()
    content_hash = models.CharField(max_length=64)  # SHA-256
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_addenda",
    )
    is_signed = models.BooleanField(default=False)

    objects = MedicalRecordsTenantManager["RecordAddendum"]()
    infrastructure_objects = InfrastructureMedicalRecordsManager["RecordAddendum"]()

    class Meta:
        db_table = "medical_records_addenda"
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "addendum_number"],
                name="unique_entry_addendum_number",
            )
        ]

    def __str__(self) -> str:
        return f"Addendum #{self.addendum_number} for Entry {self.entry_id}"
