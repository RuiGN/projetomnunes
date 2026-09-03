"""Webhook event persistence for idempotent provider processing."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel


class WebhookStatus(models.TextChoices):
    RECEIVED = "received", "Recebido"
    PROCESSED = "processed", "Processado"
    FAILED = "failed", "Falhou"
    DUPLICATE = "duplicate", "Duplicado"


class WebhookEventQuerySet(models.QuerySet["WebhookEvent"]):
    def for_clinic(self, clinic_id: UUID) -> WebhookEventQuerySet:
        return self.filter(clinic_id=clinic_id)


class WebhookEventManager(models.Manager["WebhookEvent"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("WebhookEvent queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> WebhookEventQuerySet:
        return WebhookEventQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureWebhookEventManager(models.Manager["WebhookEvent"]):
    def get_queryset(self) -> WebhookEventQuerySet:
        return WebhookEventQuerySet(self.model, using=self._db)


class WebhookEvent(UUIDTimestampedModel):
    """One sanitized provider event, deduplicated by external event id."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="webhook_events",
    )
    external_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=64)
    provider_token = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED
    )
    payload_digest = models.CharField(max_length=64, blank=True)

    objects = WebhookEventManager()
    infrastructure_objects = InfrastructureWebhookEventManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "external_event_id"),
                name="unique_webhook_event_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "created_at"),
                name="webhook_clinic_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.external_event_id}:{self.status}"
