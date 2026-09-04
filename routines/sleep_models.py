"""Models for sleep diary, cross-midnight tracking, and device telemetry (8.14.4)."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from routines.routine_models import (
    InfrastructureRoutineManager,
    RoutineTenantManager,
)


class SleepProvenance(models.TextChoices):
    SELF_REPORTED = "self_reported", "Autorrelato"
    DEVICE_IMPORTED = "device_imported", "Importado de dispositivo"
    CLINICAL_ESTIMATE = "clinical_estimate", "Estimativa descritiva"


class SleepEntry(UUIDTimestampedModel):
    """Sleep diary record supporting cross-midnight intervals and self-report."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="sleep_entries",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="sleep_entries",
    )
    reference_date = models.DateField(db_index=True)
    bedtime = models.DateTimeField()
    sleep_attempt_time = models.DateTimeField(null=True, blank=True)
    wake_time = models.DateTimeField()
    out_of_bed_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(default=0)
    perceived_quality = models.IntegerField(default=3)
    nap_duration_minutes = models.IntegerField(default=0)
    provenance = models.CharField(
        max_length=32,
        choices=SleepProvenance.choices,
        default=SleepProvenance.SELF_REPORTED,
    )
    notes = models.TextField(blank=True)
    external_record_id = models.CharField(max_length=255, blank=True)

    objects = RoutineTenantManager["SleepEntry"]()
    infrastructure_objects = InfrastructureRoutineManager["SleepEntry"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["patient_profile", "reference_date", "provenance"],
                name="unique_sleep_entry_per_patient_date_provenance",
            )
        ]
        ordering = ["-reference_date"]

    def __str__(self) -> str:
        return (
            f"Sleep {self.reference_date}: {self.duration_minutes}m ({self.provenance})"
        )


class SleepDeviceSyncRecord(UUIDTimestampedModel):
    """Device synchronization record tracking imported wearables data."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="sleep_device_sync_records",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="sleep_device_sync_records",
    )
    provider = models.CharField(max_length=64, default="apple_health")
    external_record_id = models.CharField(max_length=255)
    sync_cursor = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict)
    synced_at = models.DateTimeField(default=timezone.now)
    is_revoked = models.BooleanField(default=False)

    objects = RoutineTenantManager["SleepDeviceSyncRecord"]()
    infrastructure_objects = InfrastructureRoutineManager["SleepDeviceSyncRecord"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["patient_profile", "provider", "external_record_id"],
                name="unique_patient_device_sleep_record",
            )
        ]
        ordering = ["-synced_at"]


__all__ = [
    "SleepDeviceSyncRecord",
    "SleepEntry",
    "SleepProvenance",
]
