"""Persistence models for external integrations, adapters, credentials and webhooks."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID, uuid4

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel

_ModelT = TypeVar("_ModelT", bound=models.Model)


class IntegrationProvider(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
    MICROSOFT_OUTLOOK = "microsoft_outlook", "Microsoft Outlook"
    VIDEO_PROVIDER = "video_provider", "Provedor de Vídeo"


class CredentialStatus(models.TextChoices):
    ACTIVE = "active", "Ativa"
    PENDING = "pending", "Pendente"
    EXPIRED = "expired", "Expirada"
    REVOKED = "revoked", "Revogada"


class WebhookStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    PROCESSED = "processed", "Processado"
    FAILED = "failed", "Falha"
    DEAD_LETTER = "dead_letter", "Dead Letter"


class IntegrationQuerySet(models.QuerySet[_ModelT]):
    def for_clinic(
        self: IntegrationQuerySet[_ModelT], clinic_id: UUID
    ) -> IntegrationQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class IntegrationTenantManager(models.Manager[_ModelT]):
    def get_queryset(self) -> IntegrationQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return IntegrationQuerySet(self.model, using=self._db)
        raise RuntimeError("Integration queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: IntegrationTenantManager[_ModelT], clinic_id: UUID
    ) -> IntegrationQuerySet[_ModelT]:
        return IntegrationQuerySet(self.model, using=self._db).for_clinic(clinic_id)

    def create(self, **kwargs: Any) -> _ModelT:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return super().create(**kwargs)
        clinic_id = kwargs.get("clinic_id")
        if not clinic_id and "clinic" in kwargs:
            clinic = kwargs["clinic"]
            clinic_id = getattr(clinic, "id", clinic)
        if clinic_id:
            return self.for_clinic(clinic_id).create(**kwargs)
        return IntegrationQuerySet(self.model, using=self._db).create(**kwargs)


class InfrastructureIntegrationManager(models.Manager[_ModelT]):
    def get_queryset(
        self: InfrastructureIntegrationManager[_ModelT],
    ) -> IntegrationQuerySet[_ModelT]:
        return IntegrationQuerySet(self.model, using=self._db)


class IntegrationCredential(UUIDTimestampedModel):
    """Encrypted credential vault entry scoped to a tenant clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="integration_credentials",
    )
    provider = models.CharField(max_length=64, choices=IntegrationProvider.choices)
    name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32,
        choices=CredentialStatus.choices,
        default=CredentialStatus.PENDING,
    )
    scopes = models.JSONField(default=list, blank=True)
    encrypted_payload = models.BinaryField()
    payload_digest = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = IntegrationTenantManager["IntegrationCredential"]()
    infrastructure_objects = InfrastructureIntegrationManager["IntegrationCredential"]()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "provider", "name"],
                name="unique_credential_name_per_clinic_provider",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider}:{self.name} ({self.clinic_id})"


class WebhookEvent(UUIDTimestampedModel):
    """Inbound webhook event recorded with raw signature and sanitized payload."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="integration_webhook_events",
    )
    provider = models.CharField(max_length=64, choices=IntegrationProvider.choices)
    external_event_id = models.CharField(max_length=255)
    signature = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    source_timestamp = models.DateTimeField(null=True, blank=True)
    sanitized_payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=32,
        choices=WebhookStatus.choices,
        default=WebhookStatus.PENDING,
    )
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    objects = IntegrationTenantManager["WebhookEvent"]()
    infrastructure_objects = InfrastructureIntegrationManager["WebhookEvent"]()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_event_id"],
                name="unique_webhook_provider_event",
            )
        ]
        indexes = [
            models.Index(fields=["provider", "status", "-received_at"]),
        ]
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_event_id} ({self.status})"


class IntegrationAuditMetric(models.Model):
    """Telemetry metrics without PII for integration operations."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="integration_metrics",
    )
    provider = models.CharField(max_length=64)
    operation = models.CharField(max_length=128)
    outcome = models.CharField(max_length=32)
    latency_ms = models.IntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = IntegrationTenantManager["IntegrationAuditMetric"]()
    infrastructure_objects = InfrastructureIntegrationManager[
        "IntegrationAuditMetric"
    ]()

    class Meta:
        indexes = [
            models.Index(fields=["provider", "operation", "outcome", "-created_at"]),
        ]
        ordering = ["-created_at"]


class ExternalCalendarMapping(UUIDTimestampedModel):
    """Maps a clinic appointment to an external calendar event."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="calendar_mappings",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        related_name="calendar_mappings",
    )
    provider = models.CharField(max_length=64)
    external_calendar_id = models.CharField(max_length=255)
    external_event_id = models.CharField(max_length=255)
    version = models.IntegerField(default=1)
    sync_status = models.CharField(max_length=32, default="synced")
    last_synced_at = models.DateTimeField(auto_now=True)
    conflict_details = models.JSONField(default=dict, blank=True)

    objects = IntegrationTenantManager["ExternalCalendarMapping"]()
    infrastructure_objects = InfrastructureIntegrationManager[
        "ExternalCalendarMapping"
    ]()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "provider"],
                name="unique_appointment_calendar_provider",
            )
        ]
        ordering = ["-updated_at"]


class VideoSession(UUIDTimestampedModel):
    """Dedicated video room lifecycle tied to one clinical appointment."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="video_sessions",
    )
    appointment = models.OneToOneField(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        related_name="video_session",
    )
    provider = models.CharField(max_length=64, default="video_provider")
    room_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=32, default="pending")
    join_url = models.URLField(max_length=500)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_recording_enabled = models.BooleanField(default=False)
    fallback_url = models.URLField(max_length=500, blank=True)

    objects = IntegrationTenantManager["VideoSession"]()
    infrastructure_objects = InfrastructureIntegrationManager["VideoSession"]()

    class Meta:
        ordering = ["-created_at"]


class AppointmentSaga(UUIDTimestampedModel):
    """Transactional saga orchestrating the multi-integration appointment journey."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="appointment_sagas",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        related_name="sagas",
    )
    correlation_id = models.UUIDField(default=uuid4, unique=True)
    current_step = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default="started")
    steps_completed = models.JSONField(default=list, blank=True)
    compensation_log = models.JSONField(default=list, blank=True)
    last_error = models.TextField(blank=True)

    objects = IntegrationTenantManager["AppointmentSaga"]()
    infrastructure_objects = InfrastructureIntegrationManager["AppointmentSaga"]()

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "status", "-created_at"]),
        ]
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# Sprint 20 Enums and Models (8.20)
# ---------------------------------------------------------------------------


class ApiClientType(models.TextChoices):
    CONFIDENTIAL = "confidential", "Confidencial"
    PUBLIC_PKCE = "public_pkce", "Público com PKCE"


class ApiClientStatus(models.TextChoices):
    ACTIVE = "active", "Ativo"
    SUSPENDED = "suspended", "Suspenso"
    REVOKED = "revoked", "Revogado"


class WebhookOutboundStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    DELIVERED = "delivered", "Entregue"
    FAILED = "failed", "Falha"
    DEAD_LETTER = "dead_letter", "Dead Letter"


class CsvJobStatus(models.TextChoices):
    UPLOADED = "uploaded", "Carregado"
    PREVIEWED = "previewed", "Prévia Gerada"
    PROCESSING = "processing", "Processando"
    COMPLETED = "completed", "Concluído"
    FAILED = "failed", "Falha"


class WearableMetricType(models.TextChoices):
    STEPS = "steps", "Passos"
    RESTING_HEART_RATE = "resting_heart_rate", "Frequência Cardíaca de Repouso"
    SLEEP_DURATION_MINUTES = "sleep_duration_minutes", "Duração do Sono (min)"
    ACTIVE_MINUTES = "active_minutes", "Minutos Ativos"


class OfflineSyncStatus(models.TextChoices):
    QUEUED = "queued", "Na Fila"
    SYNCED = "synced", "Sincronizado"
    CONFLICT = "conflict", "Conflito Detectado"
    REJECTED = "rejected", "Rejeitado"


class PartnerStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    APPROVED = "approved", "Aprovado"
    SUSPENDED = "suspended", "Suspenso"
    TERMINATED = "terminated", "Encerrado"


def _default_client_id() -> str:
    return f"cli_{uuid4().hex[:16]}"


class ApiClient(UUIDTimestampedModel):
    """Registered API client/partner application scoped to a tenant clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="api_clients",
    )
    client_id = models.CharField(max_length=64, unique=True, default=_default_client_id)
    client_name = models.CharField(max_length=128)
    client_type = models.CharField(
        max_length=32,
        choices=ApiClientType.choices,
        default=ApiClientType.CONFIDENTIAL,
    )
    allowed_scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=32,
        choices=ApiClientStatus.choices,
        default=ApiClientStatus.ACTIVE,
    )
    rate_limit_rpm = models.IntegerField(default=120)
    contact_email = models.EmailField(blank=True)

    objects = IntegrationTenantManager["ApiClient"]()
    infrastructure_objects = InfrastructureIntegrationManager["ApiClient"]()

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "status", "client_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.client_name} ({self.client_id}) - {self.clinic_id}"


class ApiClientSecret(UUIDTimestampedModel):
    """Hashed secret for confidential API client with rotation history."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="api_client_secrets",
    )
    client = models.ForeignKey(
        ApiClient,
        on_delete=models.CASCADE,
        related_name="secrets",
    )
    secret_hash = models.CharField(max_length=128)
    secret_hint = models.CharField(max_length=8)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)
    rotated_at = models.DateTimeField(null=True, blank=True)

    objects = IntegrationTenantManager["ApiClientSecret"]()
    infrastructure_objects = InfrastructureIntegrationManager["ApiClientSecret"]()

    class Meta:
        ordering = ["-created_at"]


class ApiAccessToken(UUIDTimestampedModel):
    """Short-lived access token issued for an API client."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="api_access_tokens",
    )
    client = models.ForeignKey(
        ApiClient,
        on_delete=models.CASCADE,
        related_name="access_tokens",
    )
    token_hash = models.CharField(max_length=128, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    is_revoked = models.BooleanField(default=False)
    jti = models.UUIDField(default=uuid4, unique=True)

    objects = IntegrationTenantManager["ApiAccessToken"]()
    infrastructure_objects = InfrastructureIntegrationManager["ApiAccessToken"]()

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "is_revoked", "expires_at"]),
        ]
        ordering = ["-created_at"]


class ApiIdempotencyRecord(UUIDTimestampedModel):
    """Persisted idempotency payload for safe API request retries."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="api_idempotency_records",
    )
    client = models.ForeignKey(
        ApiClient,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="idempotency_records",
    )
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status_code = models.IntegerField()
    response_body = models.JSONField(default=dict)
    expires_at = models.DateTimeField()

    objects = IntegrationTenantManager["ApiIdempotencyRecord"]()
    infrastructure_objects = InfrastructureIntegrationManager["ApiIdempotencyRecord"]()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "idempotency_key"],
                name="unique_clinic_idempotency_key",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "expires_at"]),
        ]
        ordering = ["-created_at"]


class WebhookSubscription(UUIDTimestampedModel):
    """Outbound webhook subscription scoped to a clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="webhook_subscriptions",
    )
    target_url = models.URLField(max_length=500)
    secret_key = models.CharField(max_length=128)
    rotated_secret_key = models.CharField(max_length=128, blank=True)
    events_subscribed = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    max_retries = models.IntegerField(default=5)

    objects = IntegrationTenantManager["WebhookSubscription"]()
    infrastructure_objects = InfrastructureIntegrationManager["WebhookSubscription"]()

    class Meta:
        ordering = ["-created_at"]


class WebhookDeliveryAttempt(UUIDTimestampedModel):
    """Record of an outbound webhook dispatch attempt with retry/DLQ lifecycle."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="webhook_delivery_attempts",
    )
    subscription = models.ForeignKey(
        WebhookSubscription,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    event_name = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    signature_header = models.CharField(max_length=255)
    attempt_number = models.IntegerField(default=1)
    status = models.CharField(
        max_length=32,
        choices=WebhookOutboundStatus.choices,
        default=WebhookOutboundStatus.PENDING,
    )
    response_status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    scheduled_retry_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    replay_authorized_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_webhook_replays",
    )

    objects = IntegrationTenantManager["WebhookDeliveryAttempt"]()
    infrastructure_objects = InfrastructureIntegrationManager[
        "WebhookDeliveryAttempt"
    ]()

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "status", "-created_at"]),
        ]
        ordering = ["-created_at"]


class CsvImportJob(UUIDTimestampedModel):
    """Quarantined CSV import job with line-by-line validation and formula defense."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="csv_import_jobs",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="csv_imports",
    )
    template_type = models.CharField(max_length=64)
    template_version = models.CharField(max_length=16, default="1.0")
    status = models.CharField(
        max_length=32,
        choices=CsvJobStatus.choices,
        default=CsvJobStatus.UPLOADED,
    )
    total_rows = models.IntegerField(default=0)
    valid_rows = models.IntegerField(default=0)
    rejected_rows = models.IntegerField(default=0)
    quarantined_filename = models.CharField(max_length=255, blank=True)
    rejection_report = models.JSONField(default=list, blank=True)

    objects = IntegrationTenantManager["CsvImportJob"]()
    infrastructure_objects = InfrastructureIntegrationManager["CsvImportJob"]()

    class Meta:
        ordering = ["-created_at"]


class CsvExportJob(UUIDTimestampedModel):
    """CSV export job with declared purpose, row quota, and sanitized formulas."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="csv_export_jobs",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="csv_exports",
    )
    scope = models.CharField(max_length=64)
    purpose = models.CharField(max_length=255)
    encoding = models.CharField(max_length=32, default="utf-8-sig")
    status = models.CharField(
        max_length=32,
        choices=CsvJobStatus.choices,
        default=CsvJobStatus.PROCESSING,
    )
    row_count = models.IntegerField(default=0)
    expires_at = models.DateTimeField()
    file_path = models.CharField(max_length=500, blank=True)

    objects = IntegrationTenantManager["CsvExportJob"]()
    infrastructure_objects = InfrastructureIntegrationManager["CsvExportJob"]()

    class Meta:
        ordering = ["-created_at"]


class WearableConnection(UUIDTimestampedModel):
    """Opt-in patient wearable device link with immediate revocation and erasure."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="wearable_connections",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="wearable_connections",
    )
    provider = models.CharField(max_length=64)
    opt_in = models.BooleanField(default=True)
    consented_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    device_identifier = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = IntegrationTenantManager["WearableConnection"]()
    infrastructure_objects = InfrastructureIntegrationManager["WearableConnection"]()

    class Meta:
        ordering = ["-created_at"]


class WearableMetricSample(UUIDTimestampedModel):
    """Informative wearable metric sample.

    Forbidden for automated clinical decisions.
    """

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="wearable_metric_samples",
    )
    connection = models.ForeignKey(
        WearableConnection,
        on_delete=models.CASCADE,
        related_name="samples",
    )
    metric_type = models.CharField(
        max_length=64,
        choices=WearableMetricType.choices,
    )
    value = models.FloatField()
    unit = models.CharField(max_length=32)
    recorded_at = models.DateTimeField()
    provenance = models.CharField(max_length=128)
    quality_score = models.FloatField(default=1.0)
    is_informative_only = models.BooleanField(default=True, editable=False)

    objects = IntegrationTenantManager["WearableMetricSample"]()
    infrastructure_objects = InfrastructureIntegrationManager["WearableMetricSample"]()

    class Meta:
        indexes = [
            models.Index(
                fields=["clinic", "connection", "metric_type", "-recorded_at"]
            ),
        ]
        ordering = ["-recorded_at"]


class OfflineSyncQueueItem(UUIDTimestampedModel):
    """Client mutation queued offline with version check and non-silent conflict log."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="offline_sync_items",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="offline_sync_items",
    )
    device_id = models.CharField(max_length=128)
    action_type = models.CharField(max_length=64)
    idempotency_token = models.CharField(max_length=128)
    base_version = models.IntegerField(default=1)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=32,
        choices=OfflineSyncStatus.choices,
        default=OfflineSyncStatus.QUEUED,
    )
    conflict_details = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = IntegrationTenantManager["OfflineSyncQueueItem"]()
    infrastructure_objects = InfrastructureIntegrationManager["OfflineSyncQueueItem"]()

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "device_id", "status"]),
        ]
        ordering = ["-created_at"]


class PartnerSecurityAgreement(UUIDTimestampedModel):
    """Partner vendor homologation agreement with DPA, residency and exit plan."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="partner_security_agreements",
    )
    partner_name = models.CharField(max_length=128)
    dpa_signed = models.BooleanField(default=False)
    data_residency = models.CharField(max_length=16, default="BR")
    subprocessors = models.JSONField(default=list, blank=True)
    sla_tier = models.CharField(max_length=32, default="standard")
    exit_plan_documented = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_partner_agreements",
    )
    status = models.CharField(
        max_length=32,
        choices=PartnerStatus.choices,
        default=PartnerStatus.PENDING,
    )

    objects = IntegrationTenantManager["PartnerSecurityAgreement"]()
    infrastructure_objects = InfrastructureIntegrationManager[
        "PartnerSecurityAgreement"
    ]()

    class Meta:
        ordering = ["-created_at"]


class IntegrationRolloutFlag(UUIDTimestampedModel):
    """Canary rollout controller and automated rollback circuit breaker."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="rollout_flags",
    )
    feature_key = models.CharField(max_length=64)
    is_enabled = models.BooleanField(default=False)
    canary_percentage = models.IntegerField(default=0)
    error_budget_percentage = models.FloatField(default=100.0)
    rollback_triggered = models.BooleanField(default=False)
    rollback_reason = models.TextField(blank=True)

    objects = IntegrationTenantManager["IntegrationRolloutFlag"]()
    infrastructure_objects = InfrastructureIntegrationManager[
        "IntegrationRolloutFlag"
    ]()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "feature_key"],
                name="unique_clinic_integration_rollout_flag",
            )
        ]
        ordering = ["-updated_at"]


# Re-export WhatsApp and Video models for discovery by Django migrations
from .video_models import (  # noqa: E402
    VideoAccessToken,
    VideoParticipantRole,
    VideoQualityTelemetry,
    VideoSessionStatus,
)
from .whatsapp_models import (  # noqa: E402
    WhatsAppConsentRecord,
    WhatsAppConsentStatus,
    WhatsAppDeliveryStatus,
    WhatsAppInboundMessage,
    WhatsAppMessageTimeline,
    WhatsAppParsedAction,
    WhatsAppTemplate,
)

__all__ = [
    "ApiClient",
    "ApiClientSecret",
    "ApiClientStatus",
    "ApiClientType",
    "ApiAccessToken",
    "ApiIdempotencyRecord",
    "AppointmentSaga",
    "CredentialStatus",
    "CsvExportJob",
    "CsvImportJob",
    "CsvJobStatus",
    "ExternalCalendarMapping",
    "InfrastructureIntegrationManager",
    "IntegrationAuditMetric",
    "IntegrationCredential",
    "IntegrationProvider",
    "IntegrationQuerySet",
    "IntegrationRolloutFlag",
    "IntegrationTenantManager",
    "OfflineSyncQueueItem",
    "OfflineSyncStatus",
    "PartnerSecurityAgreement",
    "PartnerStatus",
    "VideoAccessToken",
    "VideoParticipantRole",
    "VideoQualityTelemetry",
    "VideoSession",
    "VideoSessionStatus",
    "WearableConnection",
    "WearableMetricSample",
    "WearableMetricType",
    "WebhookDeliveryAttempt",
    "WebhookEvent",
    "WebhookOutboundStatus",
    "WebhookStatus",
    "WebhookSubscription",
    "WhatsAppConsentRecord",
    "WhatsAppConsentStatus",
    "WhatsAppDeliveryStatus",
    "WhatsAppInboundMessage",
    "WhatsAppMessageTimeline",
    "WhatsAppParsedAction",
    "WhatsAppTemplate",
]
