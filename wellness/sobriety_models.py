"""Models for sobriety journey, craving self-reports, and support network (8.15.3)."""

from __future__ import annotations

from django.db import models

from core.persistence import UUIDTimestampedModel
from wellness.activity_models import (
    InfrastructureWellnessManager,
    WellnessTenantManager,
)


class SobrietyGoalType(models.TextChoices):
    ABSTINENCE = "abstinence", "Abstinência total"
    REDUCTION = "reduction", "Redução de danos"
    CONSCIOUS_MODERATION = "moderation", "Moderação consciente"


class SobrietyGoal(UUIDTimestampedModel):
    """Personal recovery objective respecting autonomy and neutral language."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="sobriety_goals",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="sobriety_goals",
    )
    goal_type = models.CharField(
        max_length=32,
        choices=SobrietyGoalType.choices,
        default=SobrietyGoalType.ABSTINENCE,
    )
    substance_or_behavior = models.CharField(max_length=128)
    reference_date = models.DateField()
    initial_start_date = models.DateField()
    restart_count = models.PositiveIntegerField(default=0)
    motivations = models.TextField(blank=True)
    language_preference = models.CharField(max_length=64, default="dia_a_dia")
    hide_counter = models.BooleanField(default=False)
    is_private = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    objects = WellnessTenantManager["SobrietyGoal"]()
    infrastructure_objects = InfrastructureWellnessManager["SobrietyGoal"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.substance_or_behavior} ({self.goal_type})"


class CravingCheckIn(UUIDTimestampedModel):
    """Optional craving self-report protected from lock screen exposure."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="craving_checkins",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="craving_checkins",
    )
    sobriety_goal = models.ForeignKey(
        SobrietyGoal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cravings",
    )
    intensity = models.PositiveSmallIntegerField(null=True, blank=True)
    triggers_context = models.TextField(blank=True)
    coping_strategy_used = models.TextField(blank=True)
    perceived_outcome = models.CharField(max_length=128, blank=True)
    recorded_at = models.DateTimeField()
    protected_from_lockscreen = models.BooleanField(default=True)

    objects = WellnessTenantManager["CravingCheckIn"]()
    infrastructure_objects = InfrastructureWellnessManager["CravingCheckIn"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-recorded_at"]

    def __str__(self) -> str:
        return f"Craving (intensity: {self.intensity}) at {self.recorded_at}"


class SobrietyMilestone(UUIDTimestampedModel):
    """Private personal recovery milestone without competitive leaderboards."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="sobriety_milestones",
    )
    sobriety_goal = models.ForeignKey(
        SobrietyGoal,
        on_delete=models.CASCADE,
        related_name="milestones",
    )
    days_count = models.PositiveIntegerField()
    achieved_at = models.DateField()
    recognition_title = models.CharField(max_length=128)
    is_private = models.BooleanField(default=True)

    objects = WellnessTenantManager["SobrietyMilestone"]()
    infrastructure_objects = InfrastructureWellnessManager["SobrietyMilestone"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["days_count"]

    def __str__(self) -> str:
        return f"{self.days_count} dias: {self.recognition_title}"


class SupportContact(UUIDTimestampedModel):
    """Support contact with explicit outreach consent."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="wellness_support_contacts",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="wellness_support_contacts",
    )
    name = models.CharField(max_length=128)
    relationship = models.CharField(max_length=128)
    phone_number = models.CharField(max_length=32)
    priority_order = models.PositiveSmallIntegerField(default=1)
    consent_to_reach_out = models.BooleanField(default=True)
    availability_notes = models.CharField(max_length=255, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)

    objects = WellnessTenantManager["SupportContact"]()
    infrastructure_objects = InfrastructureWellnessManager["SupportContact"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["priority_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.relationship}) - P{self.priority_order}"
