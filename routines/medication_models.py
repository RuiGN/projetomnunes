"""Models for prescribed medication adherence and safety tracking (8.14.3)."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from routines.routine_models import (
    InfrastructureRoutineManager,
    RoutineTenantManager,
)


class MedicationAdministrationRoute(models.TextChoices):
    ORAL = "oral", "Oral"
    SUBLINGUAL = "sublingual", "Sublingual"
    TOPICAL = "topical", "Tópico"
    INHALATION = "inhalation", "Inalação"
    INJECTABLE = "injectable", "Injetável"
    OPHTHALMIC = "ophthalmic", "Oftálmico"
    NASAL = "nasal", "Nasal"
    OTHER = "other", "Outro"


class MedicationLogStatus(models.TextChoices):
    TAKEN = "taken", "Tomado"
    LATE = "late", "Tomado com atraso"
    OMITTED = "omitted", "Omitido"
    NOT_REPORTED = "not_reported", "Não informado"


class PrescribedMedication(UUIDTimestampedModel):
    """User-reported representation of an external valid prescription."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="prescribed_medications",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="prescribed_medications",
    )
    medication_name = models.CharField(max_length=255)
    presentation = models.CharField(max_length=128)
    prescribed_dose = models.CharField(max_length=128)
    route = models.CharField(
        max_length=32,
        choices=MedicationAdministrationRoute.choices,
        default=MedicationAdministrationRoute.ORAL,
    )
    schedule_times = models.JSONField(default=list)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_continuous = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    prescriber_name = models.CharField(max_length=255)
    prescriber_registration = models.CharField(max_length=64)
    prescription_date = models.DateField()
    instructions = models.TextField(blank=True)
    reminder_enabled = models.BooleanField(default=True)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    objects = RoutineTenantManager["PrescribedMedication"]()
    infrastructure_objects = InfrastructureRoutineManager["PrescribedMedication"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-start_date", "medication_name"]

    def __str__(self) -> str:
        return f"{self.medication_name} ({self.prescribed_dose})"


class MedicationLog(UUIDTimestampedModel):
    """Execution and adherence log prohibiting automatic dose compensation."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medication_logs",
    )
    medication = models.ForeignKey(
        PrescribedMedication,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    scheduled_time = models.DateTimeField(db_index=True)
    actual_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=MedicationLogStatus.choices,
        default=MedicationLogStatus.NOT_REPORTED,
    )
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(default=timezone.now)

    objects = RoutineTenantManager["MedicationLog"]()
    infrastructure_objects = InfrastructureRoutineManager["MedicationLog"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["medication", "scheduled_time"],
                name="unique_medication_scheduled_log",
            )
        ]
        ordering = ["-scheduled_time"]


class MedicationConsentShare(UUIDTimestampedModel):
    """Granular consent for sharing adherence records with clinicians."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="medication_consent_shares",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="medication_consent_shares",
    )
    granted_to_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="granted_medication_shares",
    )
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = RoutineTenantManager["MedicationConsentShare"]()
    infrastructure_objects = InfrastructureRoutineManager["MedicationConsentShare"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["patient_profile", "granted_to_user"],
                name="unique_medication_share_per_patient_user",
            )
        ]
        ordering = ["-created_at"]


__all__ = [
    "MedicationAdministrationRoute",
    "MedicationConsentShare",
    "MedicationLog",
    "MedicationLogStatus",
    "PrescribedMedication",
]
