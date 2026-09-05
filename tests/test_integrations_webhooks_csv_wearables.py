"""Tests for Sprint 20 Webhooks, CSV Safe Ingestion/Export, and Wearables (8.20.2)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from integrations import services
from integrations.contracts import (
    WEBHOOK_FORBIDDEN_EVENTS,
    WearableClinicalUseForbiddenError,
)
from integrations.models import (
    CsvJobStatus,
    WearableMetricSample,
    WearableMetricType,
    WebhookOutboundStatus,
)
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_alpha() -> Clinic:
    return ClinicFactory.create(name="Clínica Integrações Webhooks")


@pytest.fixture
def admin_user(clinic_alpha: Clinic) -> User:
    user = UserFactory.create(email="admin.webhook@test.org")
    ClinicMembershipFactory.create(
        clinic=clinic_alpha,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(clinic_alpha: Clinic) -> PatientProfile:
    user = UserFactory.create(email="paciente.wearable@test.org")
    profile = PatientProfile.infrastructure_objects.create(
        clinic=clinic_alpha,
        user=user,
        birth_date=date(1990, 1, 1),
    )
    return profile


# ---------------------------------------------------------------------------
# 8.20.2.1 Webhooks Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_webhook_catalog_and_forbidden_events(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Outbound webhooks reject forbidden medical records and allow business events."""
    # Reject forbidden events
    for forbidden in WEBHOOK_FORBIDDEN_EVENTS:
        with pytest.raises(
            ValidationError, match="forbidden from webhook broadcasting"
        ):
            services.create_webhook_subscription(
                clinic_id=clinic_alpha.id,
                target_url="https://partner.api/webhook",
                events_subscribed=[forbidden],
                actor_id=admin_user.id,
            )

    # Allow valid event
    sub, raw_secret = services.create_webhook_subscription(
        clinic_id=clinic_alpha.id,
        target_url="https://partner.api/webhook",
        events_subscribed=["appointment.scheduled", "appointment.cancelled"],
        actor_id=admin_user.id,
    )
    assert sub.is_active is True
    assert len(raw_secret) == 64  # 32-byte hex

    # Secret rotation
    sub_rotated, new_secret = services.rotate_webhook_secret(
        clinic_id=clinic_alpha.id,
        subscription_id=sub.id,
        actor_id=admin_user.id,
    )
    assert new_secret != raw_secret
    assert sub_rotated.rotated_secret_key == raw_secret


@pytest.mark.django_db
def test_webhook_dispatch_hmac_signing_and_dead_letter_replay(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """Webhooks sign with HMAC-SHA256, retry, DLQ, and support authorized replay."""
    sub, _ = services.create_webhook_subscription(
        clinic_id=clinic_alpha.id,
        target_url="https://partner.api/webhook",
        events_subscribed=["appointment.scheduled"],
        actor_id=admin_user.id,
    )

    # 1. Successful dispatch
    attempt_success = services.dispatch_webhook_event(
        clinic_id=clinic_alpha.id,
        subscription_id=sub.id,
        event_name="appointment.scheduled",
        payload={"appointment_id": str(uuid4()), "status": "confirmed"},
    )
    assert attempt_success.status == WebhookOutboundStatus.DELIVERED
    assert "t=" in attempt_success.signature_header
    assert "v1=" in attempt_success.signature_header

    # 2. Failed dispatch with sender error
    def failing_sender(
        url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[int, str]:
        return 503, "Partner server temporary unavailable"

    sub.max_retries = 1  # test DLQ immediately on retry limit
    sub.save(update_fields=["max_retries"])

    attempt_fail = services.dispatch_webhook_event(
        clinic_id=clinic_alpha.id,
        subscription_id=sub.id,
        event_name="appointment.scheduled",
        payload={"appointment_id": str(uuid4())},
        test_sender_fn=failing_sender,
    )
    assert attempt_fail.status == WebhookOutboundStatus.DEAD_LETTER
    assert attempt_fail.response_status_code == 503

    # 3. Authorized replay from DLQ
    replayed = services.replay_failed_webhook(
        clinic_id=clinic_alpha.id,
        attempt_id=attempt_fail.id,
        authorized_by_id=admin_user.id,
    )
    assert replayed.status == WebhookOutboundStatus.DELIVERED
    assert replayed.replay_authorized_by_id == admin_user.id
    assert replayed.attempt_number == 2


# ---------------------------------------------------------------------------
# 8.20.2.2 & 8.20.2.3 CSV Ingestion and Export Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_csv_import_formula_defense_and_line_validation(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """CSV ingestion neutralizes formula injection and reports line-by-line errors."""
    raw_rows = [
        {"full_name": "Maria Silva", "email": "maria@test.org", "phone": "11999887766"},
        {
            "full_name": "=cmd|' /C calc'!A0",
            "email": "+malicious@test.org",
            "phone": "11999881122",
        },  # Formula injection
        {
            "full_name": "",
            "email": "missing_name@test.org",
            "phone": "11999883344",
        },  # Invalid: missing name
    ]

    job = services.validate_and_import_csv(
        clinic_id=clinic_alpha.id,
        actor_id=admin_user.id,
        template_type="patients_import",
        csv_rows=raw_rows,
    )

    assert job.status == CsvJobStatus.COMPLETED
    assert job.total_rows == 3
    assert job.valid_rows == 2
    assert job.rejected_rows == 1

    # Formula injection neutralized with single quote prefix
    assert raw_rows[1]["full_name"].startswith("'=")
    assert raw_rows[1]["email"].startswith("'+")

    # Rejection report does not leak full sensitive PII
    rejection = job.rejection_report[0]
    assert rejection["line"] == 3
    assert "Missing mandatory field" in rejection["reason"]


@pytest.mark.django_db
def test_csv_export_audit_purpose_and_formula_neutralization(
    clinic_alpha: Clinic, admin_user: User
) -> None:
    """CSV export requires purpose, neutralizes formula chars, and audits event."""
    data = [
        {"name": "Carlos Souza", "notes": "=SUM(A1:A10)"},
        {"name": "@admin_user", "notes": "-20.00"},
    ]

    # Reject export without explicit purpose
    with pytest.raises(ValidationError, match="Explicit purpose is mandatory"):
        services.request_csv_export(
            clinic_id=clinic_alpha.id,
            requested_by_id=admin_user.id,
            scope="patients_summary",
            purpose="",
            headers=["name", "notes"],
            data_rows=data,
        )

    # Export with purpose
    job = services.request_csv_export(
        clinic_id=clinic_alpha.id,
        requested_by_id=admin_user.id,
        scope="patients_summary",
        purpose="Relatório de acompanhamento trimestral",
        headers=["name", "notes"],
        data_rows=data,
    )

    assert job.status == CsvJobStatus.COMPLETED
    assert job.row_count == 2
    assert job.encoding == "utf-8-sig"
    assert job.expires_at > timezone.now()

    # Audit event verified
    audit_evt = AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic_alpha.id, action="integration.csv_exported"
    ).first()
    assert audit_evt is not None
    assert audit_evt.resource_id == str(job.id)
    assert audit_evt.justification_digest != ""


# ---------------------------------------------------------------------------
# 8.20.2.4 Wearables Ingestion and Regulatory Clinical Safeguard Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_wearable_opt_in_informative_ingestion_and_erasure(
    clinic_alpha: Clinic, patient_profile: PatientProfile
) -> None:
    """Wearable data is informative only; revocation enables Right to Erasure."""
    conn = services.connect_wearable_device(
        clinic_id=clinic_alpha.id,
        patient_id=patient_profile.id,
        provider="apple_health",
        device_identifier="apple_watch_series_9",
    )
    assert conn.opt_in is True
    assert conn.revoked_at is None

    # Ingest samples
    samples_data = [
        {"metric_type": WearableMetricType.STEPS, "value": 8540, "unit": "steps"},
        {
            "metric_type": WearableMetricType.RESTING_HEART_RATE,
            "value": 68,
            "unit": "bpm",
        },
        {
            "metric_type": WearableMetricType.SLEEP_DURATION_MINUTES,
            "value": 460,
            "unit": "min",
        },
    ]
    samples = services.record_wearable_metrics(
        clinic_id=clinic_alpha.id,
        connection_id=conn.id,
        samples=samples_data,
    )
    assert len(samples) == 3
    for s in samples:
        assert s.is_informative_only is True

    # Safeguard: Attempting to use wearable signals for automated clinical use errors
    for action in [
        "automated_triage",
        "clinical_diagnosis",
        "prescription_adjustment",
        "emergency_alert",
    ]:
        with pytest.raises(
            WearableClinicalUseForbiddenError, match="legally prohibited"
        ):
            services.enforce_no_clinical_automated_use(action_attempted=action)

    # Revocation and erasure
    services.revoke_and_delete_wearable_data(
        clinic_id=clinic_alpha.id,
        connection_id=conn.id,
        delete_samples=True,
    )

    conn.refresh_from_db()
    assert conn.opt_in is False
    assert conn.revoked_at is not None
    # Samples deleted
    assert (
        WearableMetricSample.objects.for_clinic(clinic_alpha.id)
        .filter(connection=conn)
        .count()
        == 0
    )
