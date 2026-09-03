"""Low-energy mode: temporary preference with minimal chosen actions."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel


class LowEnergyModeQuerySet(models.QuerySet["LowEnergyMode"]):
    """Tenant-scoped low-energy session queries."""

    def for_clinic(self, clinic_id: UUID) -> LowEnergyModeQuerySet:
        return self.filter(clinic_id=clinic_id)


class LowEnergyModeManager(models.Manager["LowEnergyMode"]):
    """Refuse accidental global access to low-energy sessions."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("LowEnergyMode queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> LowEnergyModeQuerySet:
        return LowEnergyModeQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureLowEnergyModeManager(models.Manager["LowEnergyMode"]):
    def get_queryset(self) -> LowEnergyModeQuerySet:
        return LowEnergyModeQuerySet(self.model, using=self._db)


class LowEnergyMode(UUIDTimestampedModel):
    """One low-energy period activated by the patient.

    The mode reduces density and shows at most three prioritized actions that
    were configured beforehand (by the patient, optionally with the
    professional). It NEVER diagnoses, escalates clinically or replaces crisis
    guidance. Non-essential notifications are suppressed while active; entries
    and reminders explicitly marked essential remain active.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="low_energy_sessions",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="low_energy_sessions",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="low_energy_sessions",
    )
    action_1 = models.CharField(max_length=255, blank=True)
    action_2 = models.CharField(max_length=255, blank=True)
    action_3 = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=500, blank=True)
    suppress_non_essential_notifications = models.BooleanField(default=True)
    started_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=64, blank=True)

    objects = LowEnergyModeManager()
    infrastructure_objects = InfrastructureLowEnergyModeManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "started_at"),
                name="lowenergy_patient_idx",
            ),
        ]

    @property
    def is_active(self) -> bool:
        """Whether the session is currently within its configured window."""
        now = timezone.now()
        if self.ended_at is not None:
            return False
        return self.started_at <= now < self.ends_at


class LowEnergyActionTemplateQuerySet(models.QuerySet["LowEnergyActionTemplate"]):
    """Tenant-scoped saved minimal-action sets (versioned)."""

    def for_clinic(self, clinic_id: UUID) -> LowEnergyActionTemplateQuerySet:
        return self.filter(clinic_id=clinic_id)


class LowEnergyActionTemplateManager(models.Manager["LowEnergyActionTemplate"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "LowEnergyActionTemplate queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> LowEnergyActionTemplateQuerySet:
        return LowEnergyActionTemplateQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureLowEnergyActionTemplateManager(
    models.Manager["LowEnergyActionTemplate"]
):
    def get_queryset(self) -> LowEnergyActionTemplateQuerySet:
        return LowEnergyActionTemplateQuerySet(self.model, using=self._db)


class LowEnergyActionTemplate(UUIDTimestampedModel):
    """Versioned set of up to three minimal actions for low-energy days."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="low_energy_action_templates",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="low_energy_action_templates",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="low_energy_action_templates",
    )
    is_active = models.BooleanField(default=True)
    version = models.PositiveSmallIntegerField(default=1)
    action_1 = models.CharField(max_length=255, blank=True)
    action_2 = models.CharField(max_length=255, blank=True)
    action_3 = models.CharField(max_length=255, blank=True)

    objects = LowEnergyActionTemplateManager()
    infrastructure_objects = InfrastructureLowEnergyActionTemplateManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "patient_profile", "version"),
                name="unique_lowenergy_template_version_per_patient",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "is_active"),
                name="lowenergy_tpl_patient_idx",
            ),
        ]
