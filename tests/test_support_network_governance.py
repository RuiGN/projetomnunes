"""Tests for governance, progressive rollout, and telemetry (8.16.5)."""

from typing import Any

import pytest

from clinics.models import Clinic
from support_network.governance_models import SupportNetworkRolloutFlag
from support_network.rollout_services import (
    check_rollout_blockers,
    is_support_feature_enabled,
    record_aggregated_metric,
)
from tests.factories import ClinicFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Governança")


@pytest.fixture
def other_clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Piloto")


@pytest.mark.django_db
def test_progressive_rollout_flags_per_tenant(
    clinic_fixture: Clinic,
    other_clinic_fixture: Clinic,
) -> None:
    SupportNetworkRolloutFlag.objects.for_clinic(clinic_fixture.id).create(
        clinic=clinic_fixture,
        feature_name="urgent_support_mode",
        is_enabled=True,
        cohort_name="GENERAL",
    )
    SupportNetworkRolloutFlag.objects.for_clinic(other_clinic_fixture.id).create(
        clinic=other_clinic_fixture,
        feature_name="urgent_support_mode",
        is_enabled=False,
        cohort_name="GENERAL",
    )

    assert (
        is_support_feature_enabled(
            clinic_id=clinic_fixture.id,
            feature_name="urgent_support_mode",
        )
        is True
    )

    assert (
        is_support_feature_enabled(
            clinic_id=other_clinic_fixture.id,
            feature_name="urgent_support_mode",
        )
        is False
    )


@pytest.mark.django_db
def test_record_pseudonymized_aggregated_metrics(
    clinic_fixture: Clinic,
) -> None:
    # First batch of telemetry
    m1 = record_aggregated_metric(
        clinic_id=clinic_fixture.id,
        invitations_sent=5,
        invitations_accepted=3,
        invitations_revoked=1,
        relationships_revoked=1,
        authorization_failures=0,
        latency_ms=45.0,
    )
    assert m1.invitations_sent == 5
    assert m1.invitations_accepted == 3
    assert m1.authorization_failures == 0

    # Second batch updates the daily aggregated metric
    m2 = record_aggregated_metric(
        clinic_id=clinic_fixture.id,
        invitations_sent=2,
        invitations_accepted=1,
        authorization_failures=2,
        latency_ms=55.0,
    )
    assert m2.invitations_sent == 7
    assert m2.invitations_accepted == 4
    assert m2.authorization_failures == 2


@pytest.mark.django_db
def test_check_rollout_blockers_on_authorization_failures(
    clinic_fixture: Clinic,
) -> None:
    # Below threshold -> pass
    record_aggregated_metric(
        clinic_id=clinic_fixture.id,
        authorization_failures=5,
    )
    assert (
        check_rollout_blockers(
            clinic_id=clinic_fixture.id,
            max_auth_failure_threshold=10,
        )
        is True
    )

    # Exceeding threshold -> blocked!
    record_aggregated_metric(
        clinic_id=clinic_fixture.id,
        authorization_failures=10,  # Total becomes 15 > 10
    )
    assert (
        check_rollout_blockers(
            clinic_id=clinic_fixture.id,
            max_auth_failure_threshold=10,
        )
        is False
    )


def test_wcag_22_aa_and_non_coercive_disclaimers() -> None:
    """Verify WCAG 2.2 AA and non-coercive copywriting invariants."""
    from support_network.urgent_plan_models import MANDATORY_URGENT_DISCLAIMER

    # Must clearly disclaim non-emergency status
    assert "não substitui serviços de emergência" in MANDATORY_URGENT_DISCLAIMER
    assert "não realiza monitoramento em tempo real" in MANDATORY_URGENT_DISCLAIMER
    assert "SAMU 192" in MANDATORY_URGENT_DISCLAIMER
    assert "CVV 188" in MANDATORY_URGENT_DISCLAIMER
