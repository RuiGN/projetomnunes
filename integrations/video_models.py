"""Models for clinical video sessions, access tokens, and quality telemetry."""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel


class VideoSessionStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    WAITING_ROOM = "waiting_room", "Sala de espera"
    IN_PROGRESS = "in_progress", "Em andamento"
    COMPLETED = "completed", "Concluída"
    CANCELED = "canceled", "Cancelada"


class VideoParticipantRole(models.TextChoices):
    THERAPIST = "therapist", "Terapeuta"
    PATIENT = "patient", "Paciente"
    OBSERVER = "observer", "Observador"


class VideoAccessToken(UUIDTimestampedModel):
    """Unguessable ephemeral access token for participant session entry."""

    session = models.ForeignKey(
        "integrations.VideoSession",
        on_delete=models.CASCADE,
        related_name="access_tokens",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_access_tokens",
    )
    role = models.CharField(
        max_length=20,
        choices=VideoParticipantRole.choices,
        default=VideoParticipantRole.PATIENT,
    )
    token = models.CharField(max_length=128, unique=True, db_index=True)
    in_waiting_room = models.BooleanField(default=False)
    device_check_completed = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    admitted_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def is_expired(self, now: datetime | None = None) -> bool:
        reference = now or timezone.now()
        return reference >= self.expires_at


class VideoQualityTelemetry(UUIDTimestampedModel):
    """Non-PII network telemetry for call quality and degradation monitoring."""

    session = models.ForeignKey(
        "integrations.VideoSession",
        on_delete=models.CASCADE,
        related_name="telemetry_records",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="video_telemetry",
    )
    packet_loss_percent = models.FloatField(default=0.0)
    jitter_ms = models.FloatField(default=0.0)
    latency_ms = models.FloatField(default=0.0)
    degradation_detected = models.BooleanField(default=False)
    contingency_activated = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at"]
