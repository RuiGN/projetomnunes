"""Models for crisis mode, emergency forwarding, and grounding exercises (8.15.5)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel
from wellness.activity_models import (
    InfrastructureWellnessManager,
    WellnessTenantManager,
)

MANDATORY_CRISIS_DISCLAIMER = (
    "Este aplicativo não é um serviço de emergência e não oferece "
    "monitoramento em tempo real. Em perigo imediato, acione agora o serviço "
    "de emergência da sua localidade."
)


class CrisisResourceConfig(UUIDTimestampedModel):
    """Clinic and country specific emergency contacts with mandatory disclaimers."""

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="crisis_resource_config",
    )
    country_code = models.CharField(max_length=4, default="BR")
    emergency_medical_number = models.CharField(max_length=16, default="192")
    emergency_fire_number = models.CharField(max_length=16, default="193")
    emotional_support_number = models.CharField(max_length=16, default="188")
    custom_helpline_name = models.CharField(max_length=128, blank=True)
    custom_helpline_number = models.CharField(max_length=32, blank=True)
    mandatory_disclaimer_text = models.TextField(default=MANDATORY_CRISIS_DISCLAIMER)

    objects = WellnessTenantManager["CrisisResourceConfig"]()
    infrastructure_objects = InfrastructureWellnessManager["CrisisResourceConfig"]()

    class Meta:
        base_manager_name = "infrastructure_objects"

    def __str__(self) -> str:
        return f"CrisisConfig for Clinic {self.clinic_id} ({self.country_code})"


class GroundingExercise(UUIDTimestampedModel):
    """De-escalation and sensory grounding exercise available offline."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="grounding_exercises",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=128)
    technique_type = models.CharField(max_length=64, default="sensory_grounding")
    instructions_markdown = models.TextField()
    steps = models.JSONField(default=list)
    duration_seconds = models.PositiveIntegerField(default=180)
    approved_by_professional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_grounding_exercises",
    )
    is_available_offline = models.BooleanField(default=True)
    can_exit_anytime = models.BooleanField(default=True)

    objects = WellnessTenantManager["GroundingExercise"]()
    infrastructure_objects = InfrastructureWellnessManager["GroundingExercise"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["title"]

    def __str__(self) -> str:
        return f"Grounding: {self.title} (offline: {self.is_available_offline})"


class CrisisAccessLog(UUIDTimestampedModel):
    """Audit log of crisis mode access and touch action confirmations."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="crisis_access_logs",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="crisis_access_logs",
    )
    accessed_at = models.DateTimeField()
    action_invoked = models.CharField(max_length=64)
    confirmation_requested = models.BooleanField(default=True)
    confirmation_granted = models.BooleanField(default=False)
    offline_mode_active = models.BooleanField(default=False)

    objects = WellnessTenantManager["CrisisAccessLog"]()
    infrastructure_objects = InfrastructureWellnessManager["CrisisAccessLog"]()

    class Meta:
        base_manager_name = "infrastructure_objects"
        ordering = ["-accessed_at"]

    def __str__(self) -> str:
        return (
            f"Crisis Log {self.action_invoked} at {self.accessed_at} "
            f"(confirmed: {self.confirmation_granted})"
        )
