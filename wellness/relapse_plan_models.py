"""Models for relapse prevention plans, granular shares, and post-lapse (8.15.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel
from wellness.activity_models import (
    InfrastructureWellnessManager,
    WellnessTenantManager,
)


class RelapsePlanSectionType(models.TextChoices):
    TRIGGERS = "triggers", "Gatilhos conhecidos"
    EARLY_WARNING_SIGNS = "early_warning_signs", "Sinais precoces de alerta"
    PROTECTIVE_FACTORS = "protective_factors", "Fatores protetores"
    COPING_STRATEGIES = "coping_strategies", "Estratégias pessoais de enfrentamento"
    SAFE_ENVIRONMENTS = "safe_environments", "Ambientes e contextos seguros"
    SUPPORT_CONTACTS = "support_contacts", "Pessoas de confiança para apoio"
    PROFESSIONAL_RESOURCES = (
        "professional_resources",
        "Recursos profissionais e serviços",
    )


class RelapsePreventionPlan(UUIDTimestampedModel):
    """Personal relapse prevention plan editable and versioned by the patient."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="relapse_plans",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="relapse_plans",
    )
    title = models.CharField(max_length=255, default="Plano de Prevenção de Recaída")
    version = models.PositiveIntegerField(default=1)
    disclaimer_acknowledged = models.BooleanField(default=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    objects = WellnessTenantManager["RelapsePreventionPlan"]()
    infrastructure_objects = InfrastructureWellnessManager["RelapsePreventionPlan"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} v{self.version} ({self.patient_profile_id})"


class RelapsePlanSection(UUIDTimestampedModel):
    """Specific section inside a relapse prevention plan."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="relapse_plan_sections",
    )
    relapse_plan = models.ForeignKey(
        RelapsePreventionPlan,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    section_type = models.CharField(
        max_length=64, choices=RelapsePlanSectionType.choices
    )
    title = models.CharField(max_length=128)
    content = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    objects = WellnessTenantManager["RelapsePlanSection"]()
    infrastructure_objects = InfrastructureWellnessManager["RelapsePlanSection"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return f"Section {self.title} ({self.section_type})"


class RelapsePlanShare(UUIDTimestampedModel):
    """Granular sharing of specific relapse plan sections with professionals/peers."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="relapse_plan_shares",
    )
    relapse_plan = models.ForeignKey(
        RelapsePreventionPlan,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    section_type = models.CharField(max_length=64, blank=True)
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_relapse_shares",
        null=True,
        blank=True,
    )
    recipient_label = models.CharField(max_length=128)
    valid_until = models.DateTimeField()
    is_revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = WellnessTenantManager["RelapsePlanShare"]()
    infrastructure_objects = InfrastructureWellnessManager["RelapsePlanShare"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Share to {self.recipient_label} (Revoked: {self.is_revoked})"


class PostLapseRecord(UUIDTimestampedModel):
    """Supportive and non-punitive post-lapse event log to resume coping strategies."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="post_lapse_records",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="post_lapse_records",
    )
    relapse_plan = models.ForeignKey(
        RelapsePreventionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="post_lapse_events",
    )
    occurred_at = models.DateTimeField()
    context_and_triggers = models.TextField()
    protective_actions_taken = models.TextField(blank=True)
    support_requested = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    objects = WellnessTenantManager["PostLapseRecord"]()
    infrastructure_objects = InfrastructureWellnessManager["PostLapseRecord"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"Post-lapse record at {self.occurred_at} ({self.patient_profile_id})"
