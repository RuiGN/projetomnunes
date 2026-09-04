"""Models for urgent support plans and local emergency resources (8.16.3)."""

from __future__ import annotations

from uuid import uuid4

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from support_network.network_models import (
    InfrastructureSupportNetworkManager,
    SupportNetworkTenantManager,
)

MANDATORY_URGENT_DISCLAIMER = (
    "Este recurso não substitui serviços de emergência médica ou psicológica e não "
    "realiza monitoramento em tempo real nem alertas automáticos. Em caso de perigo "
    "imediato, acione diretamente os serviços de urgência locais (como SAMU 192 ou "
    "CVV 188)."
)


class UrgentSupportPlan(UUIDTimestampedModel):
    """Personalized urgent support plan created voluntarily by the patient."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="urgent_support_plans",
    )
    patient = models.OneToOneField(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="urgent_support_plan",
    )
    personal_instructions = models.TextField(blank=True)
    calming_strategies = models.JSONField(default=list)
    preferred_language = models.CharField(max_length=10, default="pt-BR")
    region = models.CharField(max_length=50, default="BR")
    last_reviewed_at = models.DateTimeField(default=timezone.now)
    review_period_days = models.PositiveIntegerField(default=90)
    disclaimer_acknowledged = models.BooleanField(default=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_urgent_plans"


class UrgentSupportContact(UUIDTimestampedModel):
    """Prioritized contact to be notified consciously in times of need."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="urgent_support_contacts",
    )
    plan = models.ForeignKey(
        UrgentSupportPlan,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    priority_order = models.PositiveSmallIntegerField(default=1)
    name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=50)
    message_template = models.TextField(
        blank=True,
        default=(
            "Olá, estou em um momento difícil e gostaria de conversar ou de sua "
            "presença, quando puder."
        ),
    )
    is_active = models.BooleanField(default=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_urgent_contacts"
        ordering = ["priority_order", "created_at"]


class UrgentLocalResource(UUIDTimestampedModel):
    """Public and local emergency crisis resources and hotlines."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="local_urgent_resources",
        null=True,
        blank=True,
    )
    region = models.CharField(max_length=50, default="BR", db_index=True)
    resource_name = models.CharField(max_length=255)
    service_type = models.CharField(max_length=50)  # e.g., HOTLINE, MEDICAL, SHELTER
    contact_number = models.CharField(max_length=50)
    hours_of_operation = models.CharField(max_length=100, default="24 horas")
    is_active = models.BooleanField(default=True, db_index=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_urgent_resources"


class UrgentActionLog(UUIDTimestampedModel):
    """Immutable audit trail for conscious urgent contact actions (NO silent alerts)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="urgent_action_logs",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="urgent_action_logs",
    )
    contact_id = models.UUIDField(default=uuid4)
    action_type = models.CharField(max_length=50)
    confirmed_explicitly = models.BooleanField(default=False)
    disclaimer_shown = models.BooleanField(default=True)
    triggered_at = models.DateTimeField(default=timezone.now)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_urgent_action_logs"
        indexes = [
            models.Index(fields=["clinic", "patient", "triggered_at"]),
        ]
