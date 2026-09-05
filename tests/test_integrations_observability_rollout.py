"""Tests for Sprint 20 Observability, PHI Redaction, SLOs, WCAG 2.2 AA, and Rollout."""

from __future__ import annotations

import pytest

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from integrations import services
from integrations.models import PartnerStatus
from integrations.observability import (
    A11yValidator,
    SloTracker,
    TelemetryRedactionEngine,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Observabilidade e Rollout")


@pytest.fixture
def admin_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="admin.obs@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


# ---------------------------------------------------------------------------
# 8.20.4 Observability, Telemetry Redaction, SLOs & A11y Tests
# ---------------------------------------------------------------------------


def test_telemetry_phi_and_secret_redaction() -> None:
    """Sanitizer scrubs CPFs, emails, tokens, and clinical diagnoses."""
    raw_event = {
        "user_cpf": "123.456.789-00",
        "email_contact": "patient@hospital.org",
        "api_secret": "whsec_super_confidential_key",
        "raw_log_message": (
            "Request dispatched with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        ),
        "notes": (
            "Paciente com diagnóstico de depressão maior e "
            "prescrição de sertralina 50mg."
        ),
    }

    sanitized = TelemetryRedactionEngine.inject_correlation_context(raw_event)

    assert "trace_id" in sanitized
    assert "span_id" in sanitized
    assert sanitized["api_secret"] == "[REDACTED_SECRET]"
    assert "[REDACTED_CPF]" in sanitized["user_cpf"]
    assert "[REDACTED_EMAIL]" in sanitized["email_contact"]
    assert "[REDACTED_BEARER_TOKEN]" in sanitized["raw_log_message"]
    assert "[REDACTED_CLINICAL_PHI]" in sanitized["notes"]
    assert "sertralina" not in sanitized["notes"]


def test_slo_tracking_and_error_budget_calculation() -> None:
    """SloTracker evaluates availability, latency, webhooks, sync and error budgets."""
    # 1. Healthy production state
    healthy_report = SloTracker.evaluate_journey_slos(
        total_requests=10000,
        failed_requests=5,  # 99.95% availability (exceeds 99.9%)
        p95_latency_ms=180.0,  # <= 300 ms
        total_webhooks=1000,
        failed_webhooks=2,  # 99.8% delivery (exceeds 99.5%)
        total_syncs=5000,
        failed_syncs=1,  # 99.98% sync
    )
    assert healthy_report["all_slos_met"] is True
    assert healthy_report["availability"]["met"] is True
    assert healthy_report["latency"]["met"] is True
    assert healthy_report["exhausted_error_budget"] is False
    assert healthy_report["error_budget_remaining_percentage"] > 0

    # 2. Degraded state exhausting error budget
    degraded_report = SloTracker.evaluate_journey_slos(
        total_requests=10000,
        failed_requests=100,  # 99.0% availability (fails 99.9% target)
        p95_latency_ms=450.0,  # > 300 ms
        total_webhooks=1000,
        failed_webhooks=50,
        total_syncs=1000,
        failed_syncs=20,
    )
    assert degraded_report["all_slos_met"] is False
    assert degraded_report["exhausted_error_budget"] is True
    assert degraded_report["error_budget_remaining_percentage"] == 0.0


def test_wcag_22_aa_compliance_validation() -> None:
    """A11y validator checks contrast >= 4.5:1, keyboard nav, touch size, and ARIA."""
    # Compliant button
    good_button = {
        "element_type": "button",
        "is_interactive": True,
        "keyboard_navigable": True,
        "focus_visible": True,
        "contrast_ratio": 5.2,
        "target_width_px": 48,
        "target_height_px": 48,
        "text_content": "Confirmar Agendamento",
    }
    result_good = A11yValidator.validate_component(good_button)
    assert result_good["is_compliant"] is True
    assert len(result_good["violations"]) == 0

    # Non-compliant icon button
    bad_icon = {
        "element_type": "button",
        "is_interactive": True,
        "keyboard_navigable": False,
        "focus_visible": False,
        "contrast_ratio": 2.8,  # Below 4.5:1
        "target_width_px": 18,  # Below 24px
        "target_height_px": 18,
        "text_content": "",
        "aria_label": "",
    }
    result_bad = A11yValidator.validate_component(bad_icon)
    assert result_bad["is_compliant"] is False
    assert any("Contrast ratio" in v for v in result_bad["violations"])
    assert any("not keyboard navigable" in v for v in result_bad["violations"])
    assert any("below WCAG 2.2 min 24x24px" in v for v in result_bad["violations"])
    assert any("aria-label" in v for v in result_bad["violations"])


# ---------------------------------------------------------------------------
# 8.20.5 Partner Governance, Canary Rollout & Auto-Rollback Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_partner_homologation_dpa_and_data_residency(
    test_clinic: Clinic, admin_user: User
) -> None:
    """Partner agreement requires signed DPA, Brazil data residency and exit plan."""
    # Non-compliant partner (US data residency, no exit plan)
    non_compliant = services.evaluate_partner_homologation(
        clinic_id=test_clinic.id,
        partner_name="Global Analytics Corp",
        dpa_signed=True,
        data_residency="US",  # Violates residency
        subprocessors=["aws-us-east-1"],
        exit_plan_documented=False,
        approved_by_id=admin_user.id,
    )
    assert non_compliant.status == PartnerStatus.PENDING

    # Compliant partner
    compliant = services.evaluate_partner_homologation(
        clinic_id=test_clinic.id,
        partner_name="Laboratório Nacional BR",
        dpa_signed=True,
        data_residency="BR",
        subprocessors=["datacenter-sp"],
        exit_plan_documented=True,
        approved_by_id=admin_user.id,
    )
    assert compliant.status == PartnerStatus.APPROVED


@pytest.mark.django_db
def test_canary_rollout_and_automated_rollback_on_error_budget_exhaustion(
    test_clinic: Clinic,
) -> None:
    """Canary rollout shifts traffic; zero error budget triggers auto-rollback."""
    feature = "new_partner_webhook_dispatch"

    # Step 1: Start canary at 10%
    flag = services.update_canary_rollout(
        clinic_id=test_clinic.id,
        feature_key=feature,
        target_percentage=10,
    )
    assert flag.is_enabled is True
    assert flag.canary_percentage == 10
    assert flag.rollback_triggered is False

    # Step 2: Healthy error budget -> maintains canary
    flag = services.evaluate_rollout_health_and_auto_rollback(
        clinic_id=test_clinic.id,
        feature_key=feature,
        current_error_budget_pct=85.0,
    )
    assert flag.canary_percentage == 10
    assert flag.rollback_triggered is False

    # Step 3: Error budget exhausted (0.0%) -> triggers emergency auto-rollback!
    flag = services.evaluate_rollout_health_and_auto_rollback(
        clinic_id=test_clinic.id,
        feature_key=feature,
        current_error_budget_pct=0.0,
    )
    assert flag.is_enabled is False
    assert flag.canary_percentage == 0
    assert flag.rollback_triggered is True
    assert "Error budget exhausted" in flag.rollback_reason


@pytest.mark.django_db
def test_manual_emergency_circuit_breaker(test_clinic: Clinic) -> None:
    """Manual emergency rollback immediately resets canary traffic to 0%."""
    feature = "third_party_calendar_sync"
    services.update_canary_rollout(
        clinic_id=test_clinic.id,
        feature_key=feature,
        target_percentage=50,
    )

    flag = services.trigger_emergency_rollback(
        clinic_id=test_clinic.id,
        feature_key=feature,
        reason="Security anomaly reported on partner API credentials.",
    )
    assert flag.is_enabled is False
    assert flag.canary_percentage == 0
    assert flag.rollback_triggered is True
    assert "Security anomaly" in flag.rollback_reason
