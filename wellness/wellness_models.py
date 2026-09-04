"""Models for wellness check-ins, practice catalog, and movement plans (8.15.2)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel
from wellness.activity_models import (
    InfrastructureWellnessManager,
    WellnessTenantManager,
)


class WellnessCheckIn(UUIDTimestampedModel):
    """Optional wellness self-report without automated diagnostic inferences."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="wellness_checkins",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="wellness_checkins",
    )
    checkin_date = models.DateField()
    energy_level = models.PositiveSmallIntegerField(default=3)
    perceived_mood = models.PositiveSmallIntegerField(default=3)
    stress_level = models.PositiveSmallIntegerField(default=3)
    readiness_disposition = models.PositiveSmallIntegerField(default=3)
    context_notes = models.TextField(blank=True)
    is_shared_with_clinic = models.BooleanField(default=False)

    objects = WellnessTenantManager["WellnessCheckIn"]()
    infrastructure_objects = InfrastructureWellnessManager["WellnessCheckIn"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-checkin_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "patient_profile", "checkin_date"],
                name="unique_patient_daily_wellness_checkin",
            )
        ]

    def __str__(self) -> str:
        return f"Wellness Check-in {self.checkin_date} ({self.patient_profile_id})"


class WellnessPracticeStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    REVIEWED = "reviewed", "Revisado"
    PUBLISHED = "published", "Publicado"


class WellnessPractice(UUIDTimestampedModel):
    """Editorial library of mobility, pause, and wellness practices."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="wellness_practices",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=64, default="mobility")
    author_name = models.CharField(max_length=128)
    evidence_sources = models.TextField(blank=True)
    contraindications = models.TextField(blank=True)
    editorial_status = models.CharField(
        max_length=32,
        choices=WellnessPracticeStatus.choices,
        default=WellnessPracticeStatus.DRAFT,
    )
    valid_until = models.DateField(null=True, blank=True)

    objects = WellnessTenantManager["WellnessPractice"]()
    infrastructure_objects = InfrastructureWellnessManager["WellnessPractice"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.editorial_status})"


class MovementPlanStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PENDING_APPROVAL = "pending_approval", "Pendente de aprovação profissional"
    ACTIVE = "active", "Ativo"
    PAUSED = "paused", "Pausado"
    REVOKED = "revoked", "Revogado"


class SafeMovementPlan(UUIDTimestampedModel):
    """Individualized movement plan requiring licensed clinician approval."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="safe_movement_plans",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="safe_movement_plans",
    )
    prescribing_professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prescribed_movement_plans",
    )
    title = models.CharField(max_length=255)
    objective = models.TextField()
    target_frequency = models.CharField(max_length=64)
    target_intensity = models.CharField(max_length=64)
    progression_guidelines = models.TextField()
    adaptations = models.TextField(blank=True)
    stop_signals = models.TextField()
    status = models.CharField(
        max_length=32,
        choices=MovementPlanStatus.choices,
        default=MovementPlanStatus.DRAFT,
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_digest = models.CharField(max_length=64, blank=True)

    objects = WellnessTenantManager["SafeMovementPlan"]()
    infrastructure_objects = InfrastructureWellnessManager["SafeMovementPlan"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} - {self.status}"


class MovementPlanFeedback(UUIDTimestampedModel):
    """Patient feedback on difficulty, discomfort, or pain pausing the plan."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="movement_plan_feedbacks",
    )
    movement_plan = models.ForeignKey(
        SafeMovementPlan,
        on_delete=models.CASCADE,
        related_name="feedbacks",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="movement_plan_feedbacks",
    )
    feedback_type = models.CharField(max_length=32)
    description = models.TextField()
    occurred_at = models.DateTimeField()
    pause_plan_requested = models.BooleanField(default=True)
    requires_professional_review = models.BooleanField(default=True)

    objects = WellnessTenantManager["MovementPlanFeedback"]()
    infrastructure_objects = InfrastructureWellnessManager["MovementPlanFeedback"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"Feedback ({self.feedback_type}) for plan {self.movement_plan_id}"
