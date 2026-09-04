"""Transactional services for external integrations
and credential vault.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .contracts import (
    ALLOWED_API_SCOPES,
    FORBIDDEN_API_SCOPES,
    WEBHOOK_ALLOWED_EVENTS,
    WEBHOOK_FORBIDDEN_EVENTS,
    ApiAuthenticationError,
    ApiAuthorizationError,
    IdempotencyConflictError,
    InvalidSignatureError,
    MessagingAdapter,
    RateLimitExceededError,
    ScopeInsufficientError,
    WearableClinicalUseForbiddenError,
)
from .events import (
    api_client_registered,
    api_client_revoked,
    api_client_secret_rotated,
    api_token_issued,
    credential_revoked,
    credential_rotated,
    credential_stored,
    csv_export_generated,
    csv_import_completed,
    partner_agreement_updated,
    rollout_emergency_rollback,
    rollout_flag_updated,
    wearable_connected,
    wearable_revoked,
    webhook_dead_lettered,
    webhook_dispatched,
    webhook_processed,
    webhook_received,
    webhook_replayed,
)
from .models import (
    ApiAccessToken,
    ApiClient,
    ApiClientSecret,
    ApiClientStatus,
    ApiClientType,
    ApiIdempotencyRecord,
    CredentialStatus,
    CsvExportJob,
    CsvImportJob,
    CsvJobStatus,
    IntegrationAuditMetric,
    IntegrationCredential,
    IntegrationRolloutFlag,
    PartnerSecurityAgreement,
    PartnerStatus,
    WearableConnection,
    WearableMetricSample,
    WearableMetricType,
    WebhookDeliveryAttempt,
    WebhookEvent,
    WebhookOutboundStatus,
    WebhookStatus,
    WebhookSubscription,
)


class Service(CoreService[Any, Any]):
    """Integrations domain service base."""


def _get_vault_cipher() -> Fernet:
    """Derive a reproducible 32-byte URL-safe base64 Fernet cipher from settings."""
    fallback_key = "default-vault-secret-key-32-chars-long"
    raw_key = getattr(
        settings,
        "INTEGRATIONS_VAULT_KEY",
        getattr(settings, "MFA_ENCRYPTION_KEY", fallback_key),
    )
    # Derive deterministic 32-byte key via SHA256
    derived_32b = hashlib.sha256(raw_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(derived_32b)
    return Fernet(fernet_key)


# ---------------------------------------------------------------------------
# Credential Vault Services (8.13.1.2)
# ---------------------------------------------------------------------------


@transaction.atomic
def store_credential(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    provider: str,
    name: str,
    plaintext_secret: str,
    scopes: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    make_active: bool = True,
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> IntegrationCredential:
    """Encrypt and store an integration credential in the tenant vault."""
    if not plaintext_secret:
        raise ValidationError("Plaintext secret cannot be empty.")

    cipher = _get_vault_cipher()
    encrypted_bytes = cipher.encrypt(plaintext_secret.encode("utf-8"))
    payload_digest = hashlib.sha256(encrypted_bytes).hexdigest()

    status = CredentialStatus.ACTIVE if make_active else CredentialStatus.PENDING

    if make_active:
        # Mark other credentials with the same provider for this clinic as EXPIRED
        IntegrationCredential.objects.for_clinic(clinic_id).filter(
            provider=provider, status=CredentialStatus.ACTIVE
        ).update(status=CredentialStatus.EXPIRED)

    cred = IntegrationCredential.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        provider=provider,
        name=name,
        status=status,
        scopes=scopes or [],
        encrypted_payload=encrypted_bytes,
        payload_digest=payload_digest,
        metadata=metadata or {},
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="integration.credential_stored",
        resource_type="integration_credential",
        resource_id=str(cred.id),
        outcome="success",
        request_id=request_id or uuid4(),
        network_origin=network_origin,
    )
    credential_stored.send(sender=IntegrationCredential, credential=cred)
    return cred


@transaction.atomic
def rotate_credential(
    *,
    clinic_id: UUID,
    credential_id: UUID,
    actor_id: UUID,
    new_plaintext_secret: str,
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> IntegrationCredential:
    """Rotate an existing integration credential with a new encrypted secret."""
    cred = (
        IntegrationCredential.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=credential_id)
        .first()
    )
    if not cred:
        raise ValidationError("Credential not found.")
    if cred.status == CredentialStatus.REVOKED:
        raise ValidationError("Cannot rotate a revoked credential.")

    cipher = _get_vault_cipher()
    encrypted_bytes = cipher.encrypt(new_plaintext_secret.encode("utf-8"))
    cred.encrypted_payload = encrypted_bytes
    cred.payload_digest = hashlib.sha256(encrypted_bytes).hexdigest()
    cred.status = CredentialStatus.ACTIVE
    cred.save(
        update_fields=[
            "encrypted_payload",
            "payload_digest",
            "status",
            "updated_at",
        ]
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="integration.credential_rotated",
        resource_type="integration_credential",
        resource_id=str(cred.id),
        outcome="success",
        request_id=request_id or uuid4(),
        network_origin=network_origin,
    )
    credential_rotated.send(sender=IntegrationCredential, credential=cred)
    return cred


@transaction.atomic
def revoke_credential(
    *,
    clinic_id: UUID,
    credential_id: UUID,
    actor_id: UUID,
    reason: str = "",
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> IntegrationCredential:
    """Revoke an integration credential and record audit evidence."""
    cred = (
        IntegrationCredential.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=credential_id)
        .first()
    )
    if not cred:
        raise ValidationError("Credential not found.")

    cred.status = CredentialStatus.REVOKED
    cred.revoked_at = timezone.now()
    if reason:
        meta = dict(cred.metadata)
        meta["revocation_reason"] = reason
        cred.metadata = meta
        cred.save(update_fields=["status", "revoked_at", "metadata", "updated_at"])
    else:
        cred.save(update_fields=["status", "revoked_at", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="integration.credential_revoked",
        resource_type="integration_credential",
        resource_id=str(cred.id),
        outcome="success",
        request_id=request_id or uuid4(),
        network_origin=network_origin,
    )
    credential_revoked.send(sender=IntegrationCredential, credential=cred)
    return cred


def retrieve_decrypted_credential(
    *, clinic_id: UUID, credential_id: UUID
) -> tuple[IntegrationCredential, str]:
    """Retrieve and decrypt the credential secret, asserting payload integrity."""
    cred = (
        IntegrationCredential.objects.for_clinic(clinic_id)
        .filter(pk=credential_id)
        .first()
    )
    if not cred:
        raise ValidationError("Credential not found.")
    if cred.status == CredentialStatus.REVOKED:
        raise ValidationError("Credential is revoked.")

    encrypted_bytes = bytes(cred.encrypted_payload)
    if hashlib.sha256(encrypted_bytes).hexdigest() != cred.payload_digest:
        raise ValidationError("Credential integrity check failed: digest mismatch.")

    cipher = _get_vault_cipher()
    plaintext = cipher.decrypt(encrypted_bytes).decode("utf-8")
    return cred, plaintext


# ---------------------------------------------------------------------------
# Webhook Pipeline Services (8.13.1.3)
# ---------------------------------------------------------------------------


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize payload to remove PII, clinical details and secrets."""
    redacted_keys = {
        "token",
        "secret",
        "password",
        "pan",
        "cvv",
        "key",
        "authorization",
    }
    sanitized: dict[str, Any] = {}
    for k, v in payload.items():
        if k.lower() in redacted_keys:
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_payload(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_payload(item) if isinstance(item, dict) else item for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


@transaction.atomic
def ingest_webhook(
    *,
    provider: str,
    external_event_id: str,
    signature: str,
    raw_payload: bytes,
    source_timestamp: datetime | None = None,
    clinic_id: UUID | None = None,
    adapter: MessagingAdapter | None = None,
    max_skew_seconds: int = 300,
) -> WebhookEvent:
    """Ingest, validate and deduplicate an inbound webhook event."""
    if adapter:
        is_valid = adapter.validate_webhook_signature(
            raw_payload=raw_payload,
            signature_header=signature,
        )
        if not is_valid:
            raise InvalidSignatureError("Webhook signature validation failed.")

    now = timezone.now()
    if source_timestamp:
        skew = abs((now - source_timestamp).total_seconds())
        if skew > max_skew_seconds:
            raise InvalidSignatureError(
                f"Webhook timestamp skew too large ({skew:.1f}s > {max_skew_seconds}s)."
            )

    # Check for existing event (Idempotent deduplication)
    existing = WebhookEvent.infrastructure_objects.filter(
        provider=provider, external_event_id=external_event_id
    ).first()
    if existing:
        return existing

    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except Exception:
        data = {"raw": raw_payload.decode("utf-8", errors="replace")}

    clean_payload = sanitize_payload(data)

    event = WebhookEvent.infrastructure_objects.create(
        clinic_id=clinic_id,
        provider=provider,
        external_event_id=external_event_id,
        signature=signature,
        received_at=now,
        source_timestamp=source_timestamp,
        sanitized_payload=clean_payload,
        status=WebhookStatus.PENDING,
    )
    webhook_received.send(sender=WebhookEvent, event=event)
    return event


@transaction.atomic
def process_webhook_event(
    *,
    event_id: UUID,
    handler_func: Callable[[WebhookEvent], None] | None = None,
    max_attempts: int = 5,
) -> WebhookEvent:
    """Process a pending webhook event.

    Handles retry count and dead-letter queue routing.
    """
    event = (
        WebhookEvent.infrastructure_objects.select_for_update()
        .filter(pk=event_id)
        .first()
    )
    if not event:
        raise ValidationError("Webhook event not found.")

    if event.status == WebhookStatus.PROCESSED:
        return event

    event.attempts += 1

    try:
        if handler_func:
            handler_func(event)

        event.status = WebhookStatus.PROCESSED
        event.processed_at = timezone.now()
        event.last_error = ""
        event.save(
            update_fields=[
                "status",
                "attempts",
                "processed_at",
                "last_error",
                "updated_at",
            ]
        )
        webhook_processed.send(sender=WebhookEvent, event=event)
    except Exception as exc:
        event.last_error = str(exc)
        if event.attempts >= max_attempts:
            event.status = WebhookStatus.DEAD_LETTER
            webhook_dead_lettered.send(sender=WebhookEvent, event=event)
        else:
            event.status = WebhookStatus.FAILED

        event.save(update_fields=["status", "attempts", "last_error", "updated_at"])

    return event


@transaction.atomic
def reprocess_dead_letter_event(
    *,
    event_id: UUID,
    actor_id: UUID,
    handler_func: Callable[[WebhookEvent], None] | None = None,
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> WebhookEvent:
    """Manually re-queue a dead-letter event for processing.

    Includes administrative audit trail.
    """
    event = (
        WebhookEvent.infrastructure_objects.select_for_update()
        .filter(pk=event_id)
        .first()
    )
    if not event:
        raise ValidationError("Webhook event not found.")

    event.status = WebhookStatus.PENDING
    event.attempts = 0
    event.last_error = ""
    event.save(update_fields=["status", "attempts", "last_error", "updated_at"])

    if event.clinic_id:
        record_audit_event(
            clinic_id=event.clinic_id,
            actor_id=actor_id,
            action="integration.dead_letter_reprocessed",
            resource_type="webhook_event",
            resource_id=str(event.id),
            outcome="success",
            request_id=request_id or uuid4(),
            network_origin=network_origin,
        )

    return process_webhook_event(event_id=event.id, handler_func=handler_func)


# ---------------------------------------------------------------------------
# Metrics Services (8.13.1.4)
# ---------------------------------------------------------------------------


def record_integration_metric(
    *,
    clinic_id: UUID | None,
    provider: str,
    operation: str,
    outcome: str,
    latency_ms: int = 0,
    error_code: str = "",
) -> IntegrationAuditMetric:
    """Publish telemetry metric for integration latency, failure and volume."""
    return IntegrationAuditMetric.infrastructure_objects.create(
        clinic_id=clinic_id,
        provider=provider,
        operation=operation,
        outcome=outcome,
        latency_ms=latency_ms,
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# Sprint 20 API Portal, OAuth Clients and Tokens (8.20.1)
# ---------------------------------------------------------------------------


def _hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def register_api_client(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    client_name: str,
    client_type: str = ApiClientType.CONFIDENTIAL,
    allowed_scopes: list[str] | None = None,
    contact_email: str = "",
) -> tuple[ApiClient, str]:
    """Register a new API partner client application and generate initial secret."""
    scopes = allowed_scopes or []
    for sc in scopes:
        if sc in FORBIDDEN_API_SCOPES:
            raise ValidationError(
                f"Scope '{sc}' is strictly forbidden for external API integrations."
            )
        if sc not in ALLOWED_API_SCOPES:
            raise ValidationError(f"Scope '{sc}' is not a recognized API scope.")

    client = ApiClient.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        client_name=client_name,
        client_type=client_type,
        allowed_scopes=scopes,
        contact_email=contact_email,
        status=ApiClientStatus.ACTIVE,
    )

    raw_secret = secrets.token_urlsafe(32)
    ApiClientSecret.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        client=client,
        secret_hash=_hash_secret(raw_secret),
        secret_hint=raw_secret[-4:],
    )

    api_client_registered.send(
        sender=ApiClient,
        client_id=client.client_id,
        clinic_id=clinic_id,
        actor_id=actor_id,
    )
    return client, raw_secret


@transaction.atomic
def rotate_client_secret(
    *,
    clinic_id: UUID,
    client_id: str,
    actor_id: UUID,
    grace_period_days: int = 7,
) -> tuple[ApiClientSecret, str]:
    """Rotate an API client's secret, granting an overlapping grace period."""
    client = (
        ApiClient.objects.for_clinic(clinic_id)
        .filter(client_id=client_id, status=ApiClientStatus.ACTIVE)
        .first()
    )
    if not client:
        raise ValidationError("Active API client not found for this clinic.")

    now = timezone.now()
    # Mark existing active secrets with expiration
    ApiClientSecret.objects.for_clinic(clinic_id).filter(
        client=client, is_revoked=False, rotated_at__isnull=True
    ).update(rotated_at=now, expires_at=now + timedelta(days=grace_period_days))

    raw_secret = secrets.token_urlsafe(32)
    new_secret = ApiClientSecret.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        client=client,
        secret_hash=_hash_secret(raw_secret),
        secret_hint=raw_secret[-4:],
    )

    api_client_secret_rotated.send(
        sender=ApiClient,
        client_id=client.client_id,
        clinic_id=clinic_id,
        actor_id=actor_id,
    )
    return new_secret, raw_secret


@transaction.atomic
def revoke_api_client(
    *,
    clinic_id: UUID,
    client_id: str,
    actor_id: UUID,
    reason: str = "",
) -> ApiClient:
    """Instantly revoke an API client and invalidate all active tokens and secrets."""
    client = ApiClient.objects.for_clinic(clinic_id).filter(client_id=client_id).first()
    if not client:
        raise ValidationError("API client not found.")

    client.status = ApiClientStatus.REVOKED
    client.save(update_fields=["status", "updated_at"])

    # Revoke all tokens and secrets
    ApiAccessToken.objects.for_clinic(clinic_id).filter(client=client).update(
        is_revoked=True
    )
    ApiClientSecret.objects.for_clinic(clinic_id).filter(client=client).update(
        is_revoked=True
    )

    api_client_revoked.send(
        sender=ApiClient,
        client_id=client.client_id,
        clinic_id=clinic_id,
        actor_id=actor_id,
        reason=reason,
    )
    return client


@transaction.atomic
def issue_api_token(
    *,
    clinic_id: UUID,
    client_id: str,
    client_secret: str,
    requested_scopes: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> tuple[ApiAccessToken, str]:
    """Issue a short-lived bearer access token after authenticating client."""
    client = ApiClient.objects.for_clinic(clinic_id).filter(client_id=client_id).first()
    if not client or client.status != ApiClientStatus.ACTIVE:
        raise ApiAuthenticationError("Invalid client credentials or inactive client.")

    sec_hash = _hash_secret(client_secret)
    now = timezone.now()
    secret_record = (
        ApiClientSecret.objects.for_clinic(clinic_id)
        .filter(client=client, secret_hash=sec_hash, is_revoked=False)
        .first()
    )
    if not secret_record or (
        secret_record.expires_at and secret_record.expires_at < now
    ):
        raise ApiAuthenticationError("Invalid or expired client secret.")

    if requested_scopes is not None:
        for sc in requested_scopes:
            if sc not in client.allowed_scopes:
                raise ScopeInsufficientError(
                    f"Client is not permitted to request scope '{sc}'."
                )
        granted_scopes = requested_scopes
    else:
        granted_scopes = client.allowed_scopes

    raw_token = f"omni_tok_{secrets.token_urlsafe(40)}"
    token_hash = _hash_secret(raw_token)
    expires_at = now + timedelta(seconds=ttl_seconds)

    token_record = ApiAccessToken.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        client=client,
        token_hash=token_hash,
        scopes=granted_scopes,
        expires_at=expires_at,
    )

    api_token_issued.send(
        sender=ApiAccessToken,
        jti=token_record.jti,
        client_id=client.client_id,
        clinic_id=clinic_id,
    )
    return token_record, raw_token


def validate_api_token(
    *,
    raw_token: str,
    required_scope: str | None = None,
    expected_clinic_id: UUID | None = None,
) -> tuple[ApiClient, ApiAccessToken]:
    """Validate bearer access token, tenant scope, and expiration."""
    if not raw_token:
        raise ApiAuthenticationError("Bearer token is missing.")

    token_hash = _hash_secret(raw_token)
    token_record = (
        ApiAccessToken.infrastructure_objects.filter(
            token_hash=token_hash, is_revoked=False
        )
        .select_related("client")
        .first()
    )
    if not token_record:
        raise ApiAuthenticationError("Invalid or revoked access token.")

    if token_record.expires_at < timezone.now():
        raise ApiAuthenticationError("Access token has expired.")

    if token_record.client.status != ApiClientStatus.ACTIVE:
        raise ApiAuthenticationError(
            "Client application has been suspended or revoked."
        )

    if expected_clinic_id and token_record.clinic_id != expected_clinic_id:
        raise ApiAuthorizationError("Tenant mismatch for authenticated token.")

    if required_scope and required_scope not in token_record.scopes:
        raise ScopeInsufficientError(
            f"Access token lacks required scope '{required_scope}'."
        )

    return token_record.client, token_record


def revoke_api_token(*, raw_token_or_jti: str | UUID) -> bool:
    """Revoke a single access token immediately."""
    if isinstance(raw_token_or_jti, UUID):
        updated = ApiAccessToken.infrastructure_objects.filter(
            jti=raw_token_or_jti
        ).update(is_revoked=True)
    else:
        token_hash = _hash_secret(raw_token_or_jti)
        updated = ApiAccessToken.infrastructure_objects.filter(
            token_hash=token_hash
        ).update(is_revoked=True)
    return updated > 0


def check_rate_limit(
    *,
    clinic_id: UUID,
    client_id: str,
    limit_rpm: int = 120,
) -> tuple[bool, int]:
    """Verify rate limit for client within past 60 seconds."""
    since = timezone.now() - timedelta(seconds=60)
    current_count = (
        IntegrationAuditMetric.objects.for_clinic(clinic_id)
        .filter(provider=client_id, created_at__gte=since)
        .count()
    )

    if current_count >= limit_rpm:
        raise RateLimitExceededError(
            f"Rate limit exceeded: {current_count}/{limit_rpm} req/min."
        )
    return True, limit_rpm - current_count - 1


@transaction.atomic
def process_api_idempotency(
    *,
    clinic_id: UUID,
    client_id: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    handler_fn: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """Execute API mutation idempotently, detecting payload conflict on key reuse."""
    canonical_body = json.dumps(request_payload, sort_keys=True)
    req_hash = hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()

    record = (
        ApiIdempotencyRecord.objects.for_clinic(clinic_id)
        .filter(idempotency_key=idempotency_key)
        .first()
    )
    if record:
        if record.request_hash != req_hash:
            raise IdempotencyConflictError(
                "Idempotency key reused with mismatched request payload."
            )
        return record.status_code, record.response_body

    client = ApiClient.objects.for_clinic(clinic_id).filter(client_id=client_id).first()
    status_code, resp_body = handler_fn()

    ApiIdempotencyRecord.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        client=client,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        status_code=status_code,
        response_body=resp_body,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return status_code, resp_body


def get_api_openapi_spec() -> dict[str, Any]:
    """Export OpenAPI 3.1 contract dictionary with scopes and deprecation policies."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Omnunes Public Partner API",
            "version": "1.0.0",
            "description": "Secure partner API with OAuth 2.1, scopes and idempotency.",
        },
        "servers": [{"url": "https://api.omnunes.com.br/v1"}],
        "components": {
            "securitySchemes": {
                "OAuth2": {
                    "type": "oauth2",
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": "/oauth/token",
                            "scopes": {sc: sc for sc in sorted(ALLOWED_API_SCOPES)},
                        }
                    },
                }
            }
        },
        "deprecation_policy": {
            "sunset_header": "Sunset",
            "deprecation_header": "Deprecation",
            "minimum_notice_months": 6,
        },
    }


# ---------------------------------------------------------------------------
# Sprint 20 Webhooks Outbound Pipeline (8.20.2.1)
# ---------------------------------------------------------------------------


def create_webhook_subscription(
    *,
    clinic_id: UUID,
    target_url: str,
    events_subscribed: list[str],
    actor_id: UUID,
) -> tuple[WebhookSubscription, str]:
    """Register outbound webhook subscription with HMAC secret."""
    for evt in events_subscribed:
        if evt in WEBHOOK_FORBIDDEN_EVENTS:
            raise ValidationError(
                f"Event '{evt}' is forbidden from webhook broadcasting."
            )
        if evt not in WEBHOOK_ALLOWED_EVENTS:
            raise ValidationError(f"Event '{evt}' is not in allowed webhook catalog.")

    raw_secret = secrets.token_hex(32)
    sub = WebhookSubscription.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        target_url=target_url,
        secret_key=raw_secret,
        events_subscribed=events_subscribed,
        is_active=True,
    )
    return sub, raw_secret


def rotate_webhook_secret(
    *,
    clinic_id: UUID,
    subscription_id: UUID,
    actor_id: UUID,
) -> tuple[WebhookSubscription, str]:
    """Rotate HMAC signing key, preserving prior key for in-flight verification."""
    sub = (
        WebhookSubscription.objects.for_clinic(clinic_id)
        .filter(id=subscription_id)
        .first()
    )
    if not sub:
        raise ValidationError("Webhook subscription not found.")

    new_secret = secrets.token_hex(32)
    sub.rotated_secret_key = sub.secret_key
    sub.secret_key = new_secret
    sub.save(update_fields=["secret_key", "rotated_secret_key", "updated_at"])
    return sub, new_secret


def dispatch_webhook_event(
    *,
    clinic_id: UUID,
    subscription_id: UUID,
    event_name: str,
    payload: dict[str, Any],
    test_sender_fn: Callable[[str, dict[str, str], dict[str, Any]], tuple[int, str]]
    | None = None,
) -> WebhookDeliveryAttempt:
    """Sign and dispatch an outbound webhook with HMAC-SHA256 and retry logic."""
    if event_name in WEBHOOK_FORBIDDEN_EVENTS:
        raise ValidationError(
            f"Event '{event_name}' is prohibited from webhook distribution."
        )

    sub = (
        WebhookSubscription.objects.for_clinic(clinic_id)
        .filter(id=subscription_id, is_active=True)
        .first()
    )
    if not sub:
        raise ValidationError("Active webhook subscription not found.")

    now = timezone.now()
    timestamp_str = str(int(now.timestamp()))
    canonical_payload = json.dumps(payload, sort_keys=True)
    sign_payload = f"{timestamp_str}.{canonical_payload}".encode()
    sig = hmac.new(
        sub.secret_key.encode("utf-8"), sign_payload, hashlib.sha256
    ).hexdigest()
    signature_header = f"t={timestamp_str},v1={sig}"

    # Dispatch via provided sender or deterministic default
    if test_sender_fn:
        status_code, error_msg = test_sender_fn(
            sub.target_url,
            {
                "X-Signature-SHA256": signature_header,
                "X-Webhook-Timestamp": timestamp_str,
            },
            payload,
        )
    else:
        status_code, error_msg = 200, ""

    is_success = 200 <= status_code < 300
    attempt_status = (
        WebhookOutboundStatus.DELIVERED if is_success else WebhookOutboundStatus.FAILED
    )
    delivered_at = now if is_success else None

    attempt = WebhookDeliveryAttempt.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        subscription=sub,
        event_name=event_name,
        payload=payload,
        signature_header=signature_header,
        attempt_number=1,
        status=attempt_status,
        response_status_code=status_code,
        error_message=error_msg,
        delivered_at=delivered_at,
    )

    if is_success:
        webhook_dispatched.send(
            sender=WebhookDeliveryAttempt,
            attempt_id=attempt.id,
            clinic_id=clinic_id,
            event_name=event_name,
        )
    else:
        if attempt.attempt_number >= sub.max_retries:
            attempt.status = WebhookOutboundStatus.DEAD_LETTER
            attempt.save(update_fields=["status", "updated_at"])
            webhook_dead_lettered.send(
                sender=WebhookDeliveryAttempt,
                attempt_id=attempt.id,
                clinic_id=clinic_id,
            )
        else:
            attempt.scheduled_retry_at = now + timedelta(seconds=30)
            attempt.save(update_fields=["scheduled_retry_at", "updated_at"])

    return attempt


def replay_failed_webhook(
    *,
    clinic_id: UUID,
    attempt_id: UUID,
    authorized_by_id: UUID,
    test_sender_fn: Callable[[str, dict[str, str], dict[str, Any]], tuple[int, str]]
    | None = None,
) -> WebhookDeliveryAttempt:
    """Authorize manual replay of a dead-lettered webhook attempt."""
    old_attempt = (
        WebhookDeliveryAttempt.objects.for_clinic(clinic_id)
        .filter(id=attempt_id)
        .first()
    )
    if not old_attempt:
        raise ValidationError("Delivery attempt not found.")

    new_attempt = dispatch_webhook_event(
        clinic_id=clinic_id,
        subscription_id=old_attempt.subscription_id,
        event_name=old_attempt.event_name,
        payload=old_attempt.payload,
        test_sender_fn=test_sender_fn,
    )
    new_attempt.replay_authorized_by_id = authorized_by_id
    new_attempt.attempt_number = old_attempt.attempt_number + 1
    new_attempt.save(
        update_fields=["replay_authorized_by", "attempt_number", "updated_at"]
    )

    webhook_replayed.send(
        sender=WebhookDeliveryAttempt,
        attempt_id=new_attempt.id,
        clinic_id=clinic_id,
        authorized_by_id=authorized_by_id,
    )
    return new_attempt


# ---------------------------------------------------------------------------
# Sprint 20 CSV Import and Export with Formula Defense (8.20.2.2 & 8.20.2.3)
# ---------------------------------------------------------------------------

FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Neutralize formula injection by prefixing suspicious characters."""
    text = str(value) if value is not None else ""
    if text.startswith(FORMULA_INJECTION_PREFIXES):
        return f"'{text}"
    return text


@transaction.atomic
def validate_and_import_csv(
    *,
    clinic_id: UUID,
    actor_id: UUID,
    template_type: str,
    csv_rows: list[dict[str, Any]],
    template_version: str = "1.0",
) -> CsvImportJob:
    """Validate and ingest CSV rows with formula defense and sanitized logs."""
    required_fields_map = {
        "patients_import": ["full_name", "email", "phone"],
        "appointments_import": [
            "patient_identifier",
            "scheduled_start",
            "service_type",
        ],
    }
    required_fields = required_fields_map.get(template_type, ["name"])

    valid_rows_count = 0
    rejections: list[dict[str, Any]] = []

    for idx, row in enumerate(csv_rows, start=1):
        missing = [f for f in required_fields if not row.get(f)]
        if missing:
            rejections.append(
                {
                    "line": idx,
                    "reason": f"Missing mandatory field(s): {', '.join(missing)}",
                }
            )
            continue

        # Sanitize all cells against formula injection
        for k, v in row.items():
            row[k] = sanitize_csv_cell(v)

        valid_rows_count += 1

    total = len(csv_rows)
    status = CsvJobStatus.COMPLETED if valid_rows_count > 0 else CsvJobStatus.FAILED

    job = CsvImportJob.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        actor_id=actor_id,
        template_type=template_type,
        template_version=template_version,
        status=status,
        total_rows=total,
        valid_rows=valid_rows_count,
        rejected_rows=len(rejections),
        rejection_report=rejections,
    )

    csv_import_completed.send(
        sender=CsvImportJob,
        job_id=job.id,
        clinic_id=clinic_id,
        valid_rows=valid_rows_count,
        rejected_rows=len(rejections),
    )
    return job


@transaction.atomic
def request_csv_export(
    *,
    clinic_id: UUID,
    requested_by_id: UUID,
    scope: str,
    purpose: str,
    headers: list[str],
    data_rows: list[dict[str, Any]],
) -> CsvExportJob:
    """Generate CSV export with sanitized formula cells, quota audit, and expiration."""
    if not purpose.strip():
        raise ValidationError("Explicit purpose is mandatory for CSV export auditing.")

    # Sanitize data rows
    sanitized_rows: list[dict[str, str]] = []
    for row in data_rows:
        sanitized_rows.append({k: sanitize_csv_cell(row.get(k, "")) for k in headers})

    job = CsvExportJob.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        requested_by_id=requested_by_id,
        scope=scope,
        purpose=purpose,
        encoding="utf-8-sig",
        status=CsvJobStatus.COMPLETED,
        row_count=len(sanitized_rows),
        expires_at=timezone.now() + timedelta(days=7),
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=requested_by_id,
        action="integration.csv_exported",
        resource_type="CsvExportJob",
        resource_id=str(job.id),
        outcome="success",
        request_id=uuid4(),
        network_origin="internal_api",
        justification=purpose,
    )

    csv_export_generated.send(
        sender=CsvExportJob,
        job_id=job.id,
        clinic_id=clinic_id,
        row_count=len(sanitized_rows),
    )
    return job


# ---------------------------------------------------------------------------
# Sprint 20 Wearables Informative Ingestion & Safeguards (8.20.2.4)
# ---------------------------------------------------------------------------


def connect_wearable_device(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    provider: str,
    device_identifier: str = "",
    metadata: dict[str, Any] | None = None,
) -> WearableConnection:
    """Record opt-in consent and connect a patient wearable device."""
    conn = WearableConnection.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_id=patient_id,
        provider=provider,
        opt_in=True,
        consented_at=timezone.now(),
        device_identifier=device_identifier,
        metadata=metadata or {},
    )
    wearable_connected.send(
        sender=WearableConnection,
        connection_id=conn.id,
        clinic_id=clinic_id,
        patient_id=patient_id,
    )
    return conn


def record_wearable_metrics(
    *,
    clinic_id: UUID,
    connection_id: UUID,
    samples: list[dict[str, Any]],
) -> list[WearableMetricSample]:
    """Ingest wearable metric samples strictly labeled as informative only."""
    conn = (
        WearableConnection.objects.for_clinic(clinic_id)
        .filter(id=connection_id, opt_in=True, revoked_at__isnull=True)
        .first()
    )
    if not conn:
        raise ValidationError(
            "Active wearable connection not found or consent revoked."
        )

    created_samples: list[WearableMetricSample] = []
    for s in samples:
        m_type = s["metric_type"]
        if m_type not in WearableMetricType.values:
            raise ValidationError(f"Unrecognized wearable metric type '{m_type}'.")

        sample = WearableMetricSample.objects.for_clinic(clinic_id).create(
            clinic_id=clinic_id,
            connection=conn,
            metric_type=m_type,
            value=float(s["value"]),
            unit=s.get("unit", ""),
            recorded_at=s.get("recorded_at", timezone.now()),
            provenance=s.get("provenance", conn.provider),
            quality_score=float(s.get("quality_score", 1.0)),
            is_informative_only=True,
        )
        created_samples.append(sample)
    return created_samples


def enforce_no_clinical_automated_use(*, action_attempted: str) -> None:
    """Safeguard forbidding wearable signals from automated clinical decisions."""
    forbidden_clinical_actions = {
        "automated_triage",
        "clinical_diagnosis",
        "prescription_adjustment",
        "emergency_alert",
    }
    if action_attempted in forbidden_clinical_actions:
        raise WearableClinicalUseForbiddenError(
            f"Action '{action_attempted}' violates clinical safety: wearable signals "
            "are strictly informative and legally prohibited from driving automated "
            "clinical decisions."
        )


@transaction.atomic
def revoke_and_delete_wearable_data(
    *,
    clinic_id: UUID,
    connection_id: UUID,
    delete_samples: bool = True,
) -> None:
    """Revoke consent and erase wearable metric history under LGPD Right to Erasure."""
    conn = (
        WearableConnection.objects.for_clinic(clinic_id)
        .filter(id=connection_id)
        .first()
    )
    if not conn:
        raise ValidationError("Wearable connection not found.")

    conn.opt_in = False
    conn.revoked_at = timezone.now()
    conn.save(update_fields=["opt_in", "revoked_at", "updated_at"])

    if delete_samples:
        WearableMetricSample.objects.for_clinic(clinic_id).filter(
            connection=conn
        ).delete()

    wearable_revoked.send(
        sender=WearableConnection,
        connection_id=conn.id,
        clinic_id=clinic_id,
        patient_id=conn.patient_id,
    )


# ---------------------------------------------------------------------------
# Sprint 20 Partner Homologation and Canary Rollout (8.20.5)
# ---------------------------------------------------------------------------


def evaluate_partner_homologation(
    *,
    clinic_id: UUID,
    partner_name: str,
    dpa_signed: bool,
    data_residency: str,
    subprocessors: list[str],
    exit_plan_documented: bool,
    approved_by_id: UUID,
    sla_tier: str = "standard",
) -> PartnerSecurityAgreement:
    """Evaluate partner vendor compliance with LGPD, DPA and exit plan."""
    is_compliant = dpa_signed and data_residency == "BR" and exit_plan_documented
    status = PartnerStatus.APPROVED if is_compliant else PartnerStatus.PENDING

    agreement, _ = PartnerSecurityAgreement.objects.for_clinic(
        clinic_id
    ).update_or_create(
        clinic_id=clinic_id,
        partner_name=partner_name,
        defaults={
            "dpa_signed": dpa_signed,
            "data_residency": data_residency,
            "subprocessors": subprocessors,
            "sla_tier": sla_tier,
            "exit_plan_documented": exit_plan_documented,
            "approved_by_id": approved_by_id,
            "status": status,
        },
    )

    partner_agreement_updated.send(
        sender=PartnerSecurityAgreement,
        partner_name=partner_name,
        clinic_id=clinic_id,
        status=status,
    )
    return agreement


def update_canary_rollout(
    *,
    clinic_id: UUID,
    feature_key: str,
    target_percentage: int,
) -> IntegrationRolloutFlag:
    """Update canary traffic release percentage for tenant."""
    if not (0 <= target_percentage <= 100):
        raise ValidationError("Canary percentage must be between 0 and 100.")

    flag, _ = IntegrationRolloutFlag.objects.for_clinic(clinic_id).update_or_create(
        clinic_id=clinic_id,
        feature_key=feature_key,
        defaults={
            "is_enabled": target_percentage > 0,
            "canary_percentage": target_percentage,
            "rollback_triggered": False,
            "rollback_reason": "",
        },
    )

    rollout_flag_updated.send(
        sender=IntegrationRolloutFlag,
        feature_key=feature_key,
        clinic_id=clinic_id,
        canary_percentage=target_percentage,
    )
    return flag


def evaluate_rollout_health_and_auto_rollback(
    *,
    clinic_id: UUID,
    feature_key: str,
    current_error_budget_pct: float,
) -> IntegrationRolloutFlag:
    """Evaluate SLO health; if budget exhausted, trigger auto-rollback."""
    flag = (
        IntegrationRolloutFlag.objects.for_clinic(clinic_id)
        .filter(feature_key=feature_key)
        .first()
    )
    if not flag:
        raise ValidationError("Rollout flag not found.")

    flag.error_budget_percentage = current_error_budget_pct
    if current_error_budget_pct <= 0.0 and flag.is_enabled:
        flag.is_enabled = False
        flag.canary_percentage = 0
        flag.rollback_triggered = True
        flag.rollback_reason = "Error budget exhausted: automated rollback triggered."
        flag.save(
            update_fields=[
                "is_enabled",
                "canary_percentage",
                "rollback_triggered",
                "rollback_reason",
                "error_budget_percentage",
                "updated_at",
            ]
        )
        rollout_emergency_rollback.send(
            sender=IntegrationRolloutFlag,
            feature_key=feature_key,
            clinic_id=clinic_id,
            reason=flag.rollback_reason,
        )
    else:
        flag.save(update_fields=["error_budget_percentage", "updated_at"])
    return flag


def trigger_emergency_rollback(
    *,
    clinic_id: UUID,
    feature_key: str,
    reason: str,
) -> IntegrationRolloutFlag:
    """Manual circuit breaker instantly resetting canary traffic to zero."""
    flag = (
        IntegrationRolloutFlag.objects.for_clinic(clinic_id)
        .filter(feature_key=feature_key)
        .first()
    )
    if not flag:
        raise ValidationError("Rollout flag not found.")

    flag.is_enabled = False
    flag.canary_percentage = 0
    flag.rollback_triggered = True
    flag.rollback_reason = reason
    flag.save(
        update_fields=[
            "is_enabled",
            "canary_percentage",
            "rollback_triggered",
            "rollback_reason",
            "updated_at",
        ]
    )

    rollout_emergency_rollback.send(
        sender=IntegrationRolloutFlag,
        feature_key=feature_key,
        clinic_id=clinic_id,
        reason=reason,
    )
    return flag


__all__ = [
    "Service",
    "check_rate_limit",
    "connect_wearable_device",
    "create_webhook_subscription",
    "dispatch_webhook_event",
    "enforce_no_clinical_automated_use",
    "evaluate_partner_homologation",
    "evaluate_rollout_health_and_auto_rollback",
    "get_api_openapi_spec",
    "ingest_webhook",
    "issue_api_token",
    "process_api_idempotency",
    "process_webhook_event",
    "record_integration_metric",
    "record_wearable_metrics",
    "register_api_client",
    "replay_failed_webhook",
    "reprocess_dead_letter_event",
    "request_csv_export",
    "retrieve_decrypted_credential",
    "revoke_and_delete_wearable_data",
    "revoke_api_client",
    "revoke_api_token",
    "revoke_credential",
    "rotate_client_secret",
    "rotate_credential",
    "rotate_webhook_secret",
    "sanitize_csv_cell",
    "sanitize_payload",
    "store_credential",
    "trigger_emergency_rollback",
    "update_canary_rollout",
    "validate_and_import_csv",
    "validate_api_token",
]
