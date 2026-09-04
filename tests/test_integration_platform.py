"""Tests for integration platform, credential vault and webhook pipeline (8.13.1)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from integrations import selectors, services
from integrations.contracts import (
    FakeWhatsAppAdapter,
    InvalidSignatureError,
)
from integrations.models import (
    CredentialStatus,
    IntegrationCredential,
    WebhookEvent,
    WebhookStatus,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Integrações Teste")


@pytest.fixture
def other_clinic() -> Clinic:
    return ClinicFactory.create(name="Outra Clínica")


@pytest.fixture
def admin_user(test_clinic: Clinic):
    user = UserFactory.create(email="admin.integra@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.mark.django_db
def test_credential_vault_encryption_decryption_and_integrity(
    test_clinic: Clinic, admin_user
) -> None:
    """Credentials are encrypted at rest with envelope digest and audit evidence."""
    secret_token = "whsec_super_confidential_token_999"
    cred = services.store_credential(
        clinic_id=test_clinic.id,
        actor_id=admin_user.id,
        provider="whatsapp",
        name="Meta WhatsApp Cloud API",
        plaintext_secret=secret_token,
        scopes=["messages.send", "templates.read"],
        metadata={"phone_number_id": "10099887766"},
    )

    assert cred.status == CredentialStatus.ACTIVE
    assert cred.encrypted_payload != secret_token.encode("utf-8")
    assert cred.payload_digest != ""
    assert cred.metadata["phone_number_id"] == "10099887766"

    # Verify retrieval and decryption
    retrieved_cred, decrypted = services.retrieve_decrypted_credential(
        clinic_id=test_clinic.id, credential_id=cred.id
    )
    assert retrieved_cred.id == cred.id
    assert decrypted == secret_token

    # Verify audit event
    audit_evt = AuditEvent.infrastructure_objects.filter(
        clinic_id=test_clinic.id, action="integration.credential_stored"
    ).first()
    assert audit_evt is not None
    assert audit_evt.resource_id == str(cred.id)

    # Verify tampering triggers integrity error
    cred.encrypted_payload = b"tampered-ciphertext-payload"
    cred.save(update_fields=["encrypted_payload"])

    with pytest.raises(ValidationError, match="integrity check failed"):
        services.retrieve_decrypted_credential(
            clinic_id=test_clinic.id, credential_id=cred.id
        )


@pytest.mark.django_db
def test_credential_rotation_and_revocation(test_clinic: Clinic, admin_user) -> None:
    """Credentials can be rotated and revoked, preventing decryption once revoked."""
    cred = services.store_credential(
        clinic_id=test_clinic.id,
        actor_id=admin_user.id,
        provider="google_calendar",
        name="Conta Principal Google",
        plaintext_secret="initial_refresh_token_111",
    )

    # Rotate
    rotated = services.rotate_credential(
        clinic_id=test_clinic.id,
        credential_id=cred.id,
        actor_id=admin_user.id,
        new_plaintext_secret="new_refresh_token_222",
    )
    assert rotated.id == cred.id
    assert rotated.status == CredentialStatus.ACTIVE

    _, decrypted = services.retrieve_decrypted_credential(
        clinic_id=test_clinic.id, credential_id=cred.id
    )
    assert decrypted == "new_refresh_token_222"

    # Revoke
    revoked = services.revoke_credential(
        clinic_id=test_clinic.id,
        credential_id=cred.id,
        actor_id=admin_user.id,
        reason="Comprometimento de chave externa",
    )
    assert revoked.status == CredentialStatus.REVOKED
    assert revoked.revoked_at is not None
    assert (
        revoked.metadata.get("revocation_reason") == "Comprometimento de chave externa"
    )

    # Cannot decrypt revoked credential
    with pytest.raises(ValidationError, match="revoked"):
        services.retrieve_decrypted_credential(
            clinic_id=test_clinic.id, credential_id=cred.id
        )

    # Cannot rotate revoked credential
    with pytest.raises(ValidationError, match="Cannot rotate a revoked credential"):
        services.rotate_credential(
            clinic_id=test_clinic.id,
            credential_id=cred.id,
            actor_id=admin_user.id,
            new_plaintext_secret="another_secret",
        )


@pytest.mark.django_db
def test_credential_tenant_isolation(
    test_clinic: Clinic, other_clinic: Clinic, admin_user
) -> None:
    """Credentials are isolated per tenant and cannot be read across clinics."""
    services.store_credential(
        clinic_id=test_clinic.id,
        actor_id=admin_user.id,
        provider="whatsapp",
        name="Credencial Clínica A",
        plaintext_secret="secret_a",
    )

    # Visible to clinic A
    assert (
        selectors.active_credential_for_provider(
            clinic_id=test_clinic.id, provider="whatsapp"
        )
        is not None
    )

    # Invisible to clinic B
    assert (
        selectors.active_credential_for_provider(
            clinic_id=other_clinic.id, provider="whatsapp"
        )
        is None
    )

    # Direct query without tenant scope raises RuntimeError
    with pytest.raises(RuntimeError, match=r"\.for_clinic\(clinic_id\)"):
        list(IntegrationCredential.objects.all())


@pytest.mark.django_db
def test_webhook_ingest_signature_validation_and_sanitization(
    test_clinic: Clinic,
) -> None:
    """Webhook ingestion validates cryptographic signatures and sanitizes payloads."""
    adapter = FakeWhatsAppAdapter(secret="test-webhook-secret-key")
    raw_body = (
        b'{"id": "evt_101", "type": "message", "token": "secret_123", "text": "Ola"}'
    )

    import hashlib
    import hmac

    valid_sig = (
        "sha256="
        + hmac.new(b"test-webhook-secret-key", raw_body, hashlib.sha256).hexdigest()
    )

    # Ingest valid signature
    event = services.ingest_webhook(
        provider="whatsapp",
        external_event_id="evt_101",
        signature=valid_sig,
        raw_payload=raw_body,
        clinic_id=test_clinic.id,
        adapter=adapter,
    )
    assert event.status == WebhookStatus.PENDING
    assert event.sanitized_payload["token"] == "[REDACTED]"
    assert event.sanitized_payload["text"] == "Ola"

    # Reject invalid signature
    with pytest.raises(InvalidSignatureError, match="signature validation failed"):
        services.ingest_webhook(
            provider="whatsapp",
            external_event_id="evt_102",
            signature="sha256=invalid_signature_hex",
            raw_payload=raw_body,
            adapter=adapter,
        )

    # Reject large timestamp skew (>300s)
    too_old_timestamp = timezone.now() - timedelta(seconds=350)
    with pytest.raises(InvalidSignatureError, match="timestamp skew too large"):
        services.ingest_webhook(
            provider="whatsapp",
            external_event_id="evt_103",
            signature=valid_sig,
            raw_payload=raw_body,
            source_timestamp=too_old_timestamp,
            adapter=adapter,
            max_skew_seconds=300,
        )


@pytest.mark.django_db
def test_webhook_idempotent_deduplication(test_clinic: Clinic) -> None:
    """Ingesting an identical webhook event returns existing row without duplication."""
    raw_body = b'{"id": "evt_duplicate", "type": "delivery_receipt"}'
    first = services.ingest_webhook(
        provider="whatsapp",
        external_event_id="evt_duplicate",
        signature="",
        raw_payload=raw_body,
        clinic_id=test_clinic.id,
    )

    second = services.ingest_webhook(
        provider="whatsapp",
        external_event_id="evt_duplicate",
        signature="",
        raw_payload=raw_body,
        clinic_id=test_clinic.id,
    )

    assert first.id == second.id
    assert (
        WebhookEvent.infrastructure_objects.filter(
            provider="whatsapp", external_event_id="evt_duplicate"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_webhook_processing_retries_and_dead_letter(
    test_clinic: Clinic, admin_user
) -> None:
    """Transient webhook failures retry; terminal failures move to dead-letter queue."""
    raw_body = b'{"id": "evt_fail", "type": "test_failure"}'
    event = services.ingest_webhook(
        provider="whatsapp",
        external_event_id="evt_fail",
        signature="",
        raw_payload=raw_body,
        clinic_id=test_clinic.id,
    )

    def failing_handler(evt: WebhookEvent) -> None:
        raise ConnectionError("External provider down")

    # Attempt 1
    event = services.process_webhook_event(
        event_id=event.id, handler_func=failing_handler, max_attempts=2
    )
    assert event.attempts == 1
    assert event.status == WebhookStatus.FAILED
    assert "External provider down" in event.last_error

    # Attempt 2 -> Terminal Dead Letter
    event = services.process_webhook_event(
        event_id=event.id, handler_func=failing_handler, max_attempts=2
    )
    assert event.attempts == 2
    assert event.status == WebhookStatus.DEAD_LETTER

    # Dead letter shows in selector
    dl_events = selectors.dead_letter_webhooks(clinic_id=test_clinic.id)
    assert len(dl_events) == 1
    assert dl_events[0].id == event.id

    # Reprocess dead letter with recovered handler
    called = []

    def healthy_handler(evt: WebhookEvent) -> None:
        called.append(evt.id)

    reprocessed = services.reprocess_dead_letter_event(
        event_id=event.id,
        actor_id=admin_user.id,
        handler_func=healthy_handler,
    )
    assert reprocessed.status == WebhookStatus.PROCESSED
    assert len(called) == 1


@pytest.mark.django_db
def test_integration_telemetry_metrics(test_clinic: Clinic) -> None:
    """Metrics aggregate telemetry without storing clinical data or PII."""
    services.record_integration_metric(
        clinic_id=test_clinic.id,
        provider="whatsapp",
        operation="send_template",
        outcome="success",
        latency_ms=120,
    )
    services.record_integration_metric(
        clinic_id=test_clinic.id,
        provider="whatsapp",
        operation="send_template",
        outcome="failure",
        latency_ms=350,
        error_code="RATE_LIMIT",
    )

    summary = selectors.metrics_summary_for_clinic(clinic_id=test_clinic.id)
    assert summary["total_operations"] == 2
    assert summary["successful_operations"] == 1
    assert summary["failed_operations"] == 1
    assert summary["success_rate"] == 50.0
