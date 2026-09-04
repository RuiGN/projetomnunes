"""Models for clinical care plans and patient autonomous supervision.

Part of feature 8.14.5.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from routines.routine_models import (
    InfrastructureRoutineManager,
    RoutineTenantManager,
)


class CarePlanStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PENDING_SIGNATURE = (
        "pending_signature",
        "Aguardando assinatura profissional",
    )
    ACTIVE = "active", "Ativo"
    PAUSED = "paused", "Pausado"
    COMPLETED = "completed", "Concluído"
    REVOKED = "revoked", "Revogado"


class PatientResponseChoice(models.TextChoices):
    ACCEPTED = "accepted", "Aceito"
    REFUSED = "refused", "Recusado"
    PAUSED = "paused", "Pausado pelo paciente"
    REVIEW_REQUESTED = "review_requested", "Revisão solicitada"


class CarePlan(UUIDTimestampedModel):
    """Clinical care plan proposed by a licensed healthcare professional."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="care_plans",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="care_plans",
    )
    prescribing_professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prescribed_care_plans",
    )
    title = models.CharField(max_length=255)
    objective = models.TextField()
    clinical_rationale = models.TextField()
    contraindications = models.TextField(blank=True)
    status = models.CharField(
        max_length=32,
        choices=CarePlanStatus.choices,
        default=CarePlanStatus.DRAFT,
    )
    version = models.IntegerField(default=1)
    valid_from = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_digest = models.CharField(max_length=64, blank=True)

    objects = RoutineTenantManager["CarePlan"]()
    infrastructure_objects = InfrastructureRoutineManager["CarePlan"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} (v{self.version}) - {self.status}"


class CarePlanAction(UUIDTimestampedModel):
    """Targeted habit, activity, or behavioral recommendation inside a care
    plan.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="care_plan_actions",
    )
    care_plan = models.ForeignKey(
        CarePlan,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action_description = models.CharField(max_length=255)
    target_frequency = models.CharField(max_length=64, default="daily")
    guidance = models.TextField(blank=True)
    is_mandatory = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    objects = RoutineTenantManager["CarePlanAction"]()
    infrastructure_objects = InfrastructureRoutineManager["CarePlanAction"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["order", "created_at"]


class CarePlanPatientResponse(UUIDTimestampedModel):
    """Immutable record of patient autonomous response to a presented care
    plan version.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="care_plan_patient_responses",
    )
    care_plan = models.ForeignKey(
        CarePlan,
        on_delete=models.CASCADE,
        related_name="patient_responses",
    )
    plan_version_reviewed = models.IntegerField()
    decision = models.CharField(
        max_length=32,
        choices=PatientResponseChoice.choices,
    )
    patient_notes = models.TextField(blank=True)
    responded_at = models.DateTimeField(default=timezone.now)

    objects = RoutineTenantManager["CarePlanPatientResponse"]()
    infrastructure_objects = InfrastructureRoutineManager["CarePlanPatientResponse"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-responded_at"]


__all__ = [
    "CarePlan",
    "CarePlanAction",
    "CarePlanPatientResponse",
    "CarePlanStatus",
    "PatientResponseChoice",
]
