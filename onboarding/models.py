"""Onboarding persistence owned by the onboarding domain."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel


class PatientOnboardingQuerySet(models.QuerySet["PatientOnboarding"]):
    """Patient onboarding records retaining explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> PatientOnboardingQuerySet:
        return self.filter(clinic_id=clinic_id)


class PatientOnboardingManager(models.Manager["PatientOnboarding"]):
    """Refuse accidental global access to onboarding records."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PatientOnboarding queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PatientOnboardingQuerySet:
        return PatientOnboardingQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructurePatientOnboardingManager(models.Manager["PatientOnboarding"]):
    """Unrestricted onboarding access reserved for transactional services."""

    def get_queryset(self) -> PatientOnboardingQuerySet:
        return PatientOnboardingQuerySet(self.model, using=self._db)


class PatientOnboarding(UUIDTimestampedModel):
    """Patient-declared goals and preferences collected through onboarding."""

    class Step(models.TextChoices):
        GOALS = "goals", "Objetivos"
        PREFERENCES = "preferences", "Preferências"
        TERMS = "terms", "Termos e limites"
        COMPLETE = "complete", "Concluído"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="patient_onboardings",
    )
    patient_profile = models.OneToOneField(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    goals = models.JSONField(default=list, blank=True)
    contact_preferences = models.JSONField(default=dict, blank=True)
    reminder_windows = models.JSONField(default=dict, blank=True)
    current_step = models.CharField(max_length=32, choices=Step, default=Step.GOALS)
    completed_at = models.DateTimeField(blank=True, null=True)

    objects = PatientOnboardingManager()
    infrastructure_objects = InfrastructurePatientOnboardingManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "current_step"),
                name="onboarding_clinic_step_idx",
            )
        ]
