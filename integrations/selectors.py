"""Read selectors for the external integrations domain."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.selectors import Selector as CoreSelector

from .models import (
    ApiAccessToken,
    ApiClient,
    ApiIdempotencyRecord,
    AppointmentSaga,
    CredentialStatus,
    CsvExportJob,
    CsvImportJob,
    ExternalCalendarMapping,
    IntegrationAuditMetric,
    IntegrationCredential,
    IntegrationRolloutFlag,
    OfflineSyncQueueItem,
    PartnerSecurityAgreement,
    VideoSession,
    WearableConnection,
    WearableMetricSample,
    WebhookDeliveryAttempt,
    WebhookEvent,
    WebhookStatus,
    WebhookSubscription,
)


class Selector(CoreSelector[Any, Any]):
    """Integrations domain selector."""


def active_credential_for_provider(
    *, clinic_id: UUID, provider: str
) -> IntegrationCredential | None:
    """Return the primary active credential for a given provider in a clinic."""
    return (
        IntegrationCredential.objects.for_clinic(clinic_id)
        .filter(provider=provider, status=CredentialStatus.ACTIVE)
        .first()
    )


def credentials_for_clinic(*, clinic_id: UUID) -> list[IntegrationCredential]:
    """List all credentials configured for a clinic."""
    return list(
        IntegrationCredential.objects.for_clinic(clinic_id).order_by("provider", "name")
    )


def webhook_event_by_id(
    *, provider: str, external_event_id: str
) -> WebhookEvent | None:
    """Retrieve an inbound webhook by provider and external ID.

    Uses the infrastructure manager for deduplication.
    """
    return WebhookEvent.infrastructure_objects.filter(
        provider=provider, external_event_id=external_event_id
    ).first()


def pending_webhooks(
    *, provider: str | None = None, limit: int = 50
) -> list[WebhookEvent]:
    """Retrieve pending webhook events eligible for processing."""
    qs = WebhookEvent.infrastructure_objects.filter(status=WebhookStatus.PENDING)
    if provider:
        qs = qs.filter(provider=provider)
    return list(qs.order_by("received_at")[:limit])


def dead_letter_webhooks(
    *, clinic_id: UUID | None = None, limit: int = 50
) -> list[WebhookEvent]:
    """Retrieve webhook events parked in dead-letter queue for review."""
    qs = WebhookEvent.infrastructure_objects.filter(status=WebhookStatus.DEAD_LETTER)
    if clinic_id:
        qs = qs.filter(clinic_id=clinic_id)
    return list(qs.order_by("-received_at")[:limit])


def calendar_mapping_for_appointment(
    *, clinic_id: UUID, appointment_id: UUID, provider: str = "google_calendar"
) -> ExternalCalendarMapping | None:
    """Retrieve external calendar mapping for an appointment."""
    return (
        ExternalCalendarMapping.objects.for_clinic(clinic_id)
        .filter(appointment_id=appointment_id, provider=provider)
        .first()
    )


def video_session_for_appointment(
    *, clinic_id: UUID, appointment_id: UUID
) -> VideoSession | None:
    """Retrieve video session for an appointment."""
    return (
        VideoSession.objects.for_clinic(clinic_id)
        .filter(appointment_id=appointment_id)
        .first()
    )


def active_sagas_for_clinic(*, clinic_id: UUID) -> list[AppointmentSaga]:
    """Retrieve in-flight or failed sagas for clinic operations."""
    return list(
        AppointmentSaga.objects.for_clinic(clinic_id)
        .filter(status__in=["started", "in_progress", "failed"])
        .order_by("-created_at")
    )


def saga_by_correlation_id(*, correlation_id: UUID) -> AppointmentSaga | None:
    """Retrieve a saga by correlation ID."""
    return AppointmentSaga.infrastructure_objects.filter(
        correlation_id=correlation_id
    ).first()


def metrics_summary_for_clinic(*, clinic_id: UUID) -> dict[str, Any]:
    """Compute aggregate telemetry for clinic integrations."""
    metrics = IntegrationAuditMetric.objects.for_clinic(clinic_id)
    total_ops = metrics.count()
    success_ops = metrics.filter(outcome="success").count()
    failure_ops = metrics.filter(outcome="failure").count()
    rate_limited_ops = metrics.filter(outcome="rate_limited").count()

    return {
        "total_operations": total_ops,
        "successful_operations": success_ops,
        "failed_operations": failure_ops,
        "rate_limited_operations": rate_limited_ops,
        "success_rate": (success_ops / total_ops * 100.0) if total_ops > 0 else 100.0,
    }


def get_api_client(*, clinic_id: UUID, client_id: str) -> ApiClient | None:
    """Retrieve an API client scoped to a clinic by its public client_id."""
    return ApiClient.objects.for_clinic(clinic_id).filter(client_id=client_id).first()


def list_api_clients(*, clinic_id: UUID) -> list[ApiClient]:
    """List all registered API clients for a tenant clinic."""
    return list(ApiClient.objects.for_clinic(clinic_id).order_by("-created_at"))


def get_api_token_by_hash(*, token_hash: str) -> ApiAccessToken | None:
    """Retrieve an access token by its SHA256 hash using infrastructure manager."""
    return ApiAccessToken.infrastructure_objects.filter(
        token_hash=token_hash, is_revoked=False
    ).first()


def get_idempotency_record(
    *, clinic_id: UUID, idempotency_key: str
) -> ApiIdempotencyRecord | None:
    """Retrieve persisted idempotency record for tenant and key."""
    return (
        ApiIdempotencyRecord.objects.for_clinic(clinic_id)
        .filter(idempotency_key=idempotency_key)
        .first()
    )


def get_webhook_subscription(
    *, clinic_id: UUID, subscription_id: UUID
) -> WebhookSubscription | None:
    """Retrieve outbound webhook subscription by ID."""
    return (
        WebhookSubscription.objects.for_clinic(clinic_id)
        .filter(id=subscription_id)
        .first()
    )


def list_webhook_subscriptions(*, clinic_id: UUID) -> list[WebhookSubscription]:
    """List outbound webhook subscriptions for a clinic."""
    return list(
        WebhookSubscription.objects.for_clinic(clinic_id).order_by("-created_at")
    )


def list_webhook_delivery_attempts(
    *,
    clinic_id: UUID,
    subscription_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[WebhookDeliveryAttempt]:
    """List delivery attempts for outbound webhooks."""
    qs = WebhookDeliveryAttempt.objects.for_clinic(clinic_id)
    if subscription_id:
        qs = qs.filter(subscription_id=subscription_id)
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("-created_at")[:limit])


def get_csv_import_job(*, clinic_id: UUID, job_id: UUID) -> CsvImportJob | None:
    """Retrieve CSV import job."""
    return CsvImportJob.objects.for_clinic(clinic_id).filter(id=job_id).first()


def get_csv_export_job(*, clinic_id: UUID, job_id: UUID) -> CsvExportJob | None:
    """Retrieve CSV export job."""
    return CsvExportJob.objects.for_clinic(clinic_id).filter(id=job_id).first()


def get_wearable_connection(
    *, clinic_id: UUID, patient_id: UUID
) -> WearableConnection | None:
    """Retrieve active wearable connection for a patient."""
    return (
        WearableConnection.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_id, opt_in=True, revoked_at__isnull=True)
        .first()
    )


def list_wearable_samples(
    *,
    clinic_id: UUID,
    connection_id: UUID,
    metric_type: str | None = None,
    limit: int = 100,
) -> list[WearableMetricSample]:
    """List wearable metric samples for a connection."""
    qs = WearableMetricSample.objects.for_clinic(clinic_id).filter(
        connection_id=connection_id
    )
    if metric_type:
        qs = qs.filter(metric_type=metric_type)
    return list(qs.order_by("-recorded_at")[:limit])


def get_offline_queue_items(
    *, clinic_id: UUID, device_id: str, status: str | None = None
) -> list[OfflineSyncQueueItem]:
    """List offline sync mutations for a client device."""
    qs = OfflineSyncQueueItem.objects.for_clinic(clinic_id).filter(device_id=device_id)
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("created_at"))


def get_partner_agreement(
    *, clinic_id: UUID, partner_name: str
) -> PartnerSecurityAgreement | None:
    """Retrieve partner agreement by name for clinic."""
    return (
        PartnerSecurityAgreement.objects.for_clinic(clinic_id)
        .filter(partner_name=partner_name)
        .first()
    )


def get_rollout_flag(
    *, clinic_id: UUID, feature_key: str
) -> IntegrationRolloutFlag | None:
    """Retrieve canary rollout flag for clinic."""
    return (
        IntegrationRolloutFlag.objects.for_clinic(clinic_id)
        .filter(feature_key=feature_key)
        .first()
    )


__all__ = [
    "Selector",
    "active_credential_for_provider",
    "active_sagas_for_clinic",
    "calendar_mapping_for_appointment",
    "credentials_for_clinic",
    "dead_letter_webhooks",
    "get_api_client",
    "get_api_token_by_hash",
    "get_csv_export_job",
    "get_csv_import_job",
    "get_idempotency_record",
    "get_offline_queue_items",
    "get_partner_agreement",
    "get_rollout_flag",
    "get_wearable_connection",
    "get_webhook_subscription",
    "list_api_clients",
    "list_wearable_samples",
    "list_webhook_delivery_attempts",
    "list_webhook_subscriptions",
    "metrics_summary_for_clinic",
    "pending_webhooks",
    "saga_by_correlation_id",
    "video_session_for_appointment",
    "webhook_event_by_id",
]
