"""Models for physical activity logging and wearable synchronization (8.15.1)."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel

_ModelT = TypeVar("_ModelT", bound=models.Model)


class WellnessQuerySet(models.QuerySet[_ModelT]):
    """Tenant-scoped query set for wellness domain models."""

    def for_clinic(
        self: WellnessQuerySet[_ModelT], clinic_id: UUID
    ) -> WellnessQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class WellnessTenantManager(models.Manager[_ModelT]):
    """Tenant-safe default manager requiring an explicit clinic scope."""

    def get_queryset(self) -> WellnessQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return WellnessQuerySet(self.model, using=self._db)
        raise RuntimeError("Wellness queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: WellnessTenantManager[_ModelT], clinic_id: UUID
    ) -> WellnessQuerySet[_ModelT]:
        return WellnessQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureWellnessManager(models.Manager[_ModelT]):
    """Unrestricted wellness access for internal workers and testing."""

    def get_queryset(
        self: InfrastructureWellnessManager[_ModelT],
    ) -> WellnessQuerySet[_ModelT]:
        return WellnessQuerySet(self.model, using=self._db)


class ActivityIntensity(models.TextChoices):
    VERY_LIGHT = "very_light", "Muito leve"
    LIGHT = "light", "Leve"
    MODERATE = "moderate", "Moderada"
    VIGOROUS = "vigorous", "Vigorosa"
    MAXIMAL = "maximal", "Máxima"


class ActivityProvenance(models.TextChoices):
    SELF_REPORTED = "self_reported", "Autorrelato"
    DEVICE_IMPORTED = "device_imported", "Importado de dispositivo"


class ActivityLog(UUIDTimestampedModel):
    """Physical activity record supporting accessible and assisted modalities."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    activity_type = models.CharField(max_length=64)
    is_accessible_assisted = models.BooleanField(default=False)
    start_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField()
    perceived_intensity = models.CharField(
        max_length=32,
        choices=ActivityIntensity.choices,
        default=ActivityIntensity.MODERATE,
    )
    rpe_scale = models.PositiveSmallIntegerField(default=4)
    distance_meters = models.PositiveIntegerField(null=True, blank=True)
    adaptations = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    provenance = models.CharField(
        max_length=32,
        choices=ActivityProvenance.choices,
        default=ActivityProvenance.SELF_REPORTED,
    )
    external_record_id = models.CharField(max_length=128, blank=True, db_index=True)
    is_overlapping_consolidated = models.BooleanField(default=False)
    is_preferred_in_trends = models.BooleanField(default=True)

    objects = WellnessTenantManager["ActivityLog"]()
    infrastructure_objects = InfrastructureWellnessManager["ActivityLog"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-start_time"]

    def __str__(self) -> str:
        return f"{self.activity_type} ({self.duration_minutes}m) - {self.provenance}"


class ActivityDeviceSyncRecord(UUIDTimestampedModel):
    """Telemetry sync tracking for wearables with incremental cursor."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="activity_sync_records",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="activity_sync_records",
    )
    device_provider = models.CharField(max_length=64)
    sync_cursor = models.CharField(max_length=255, blank=True)
    last_synced_at = models.DateTimeField()
    records_synced_count = models.PositiveIntegerField(default=0)
    is_connection_revoked = models.BooleanField(default=False)
    scopes_granted = models.JSONField(default=list)

    objects = WellnessTenantManager["ActivityDeviceSyncRecord"]()
    infrastructure_objects = InfrastructureWellnessManager["ActivityDeviceSyncRecord"]()

    class Meta:
        base_manager_name = "infrastructure_objects"

    def __str__(self) -> str:
        return f"{self.device_provider} sync ({self.records_synced_count} records)"
