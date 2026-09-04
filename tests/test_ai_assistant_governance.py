"""Tests for AI model governance, benchmark evaluation and inventory (PRD 8.19.3)."""

from typing import Any

import pytest

from ai_assistant.contracts import RiskTier
from ai_assistant.models import (
    AiEvaluationBenchmark,
    AiModelInventory,
)
from ai_assistant.selectors import (
    get_latest_evaluation_run,
    get_model_inventory,
    list_approved_models,
)
from ai_assistant.services import evaluate_model_run
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Governança IA")


@pytest.fixture
def admin_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="admin_gov_ia@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.fixture
def model_v1(db: Any, admin_user: Any) -> AiModelInventory:
    return AiModelInventory.objects.create(
        name="ClinicalDraft-LLM",
        version="1.0.0",
        provider="InternalSecureHost",
        processing_region="sa-east-1",
        legal_basis="Legítimo Interesse",
        risk_tier=RiskTier.LOW.value,
        approved_by=admin_user,
        reevaluation_date="2027-01-01",
        is_active=True,
    )


@pytest.fixture
def benchmark(db: Any) -> AiEvaluationBenchmark:
    return AiEvaluationBenchmark.objects.create(
        name="ClinicalSynthesisBenchmark-BR",
        dataset_version="2026.1",
        cases_json=[
            {"id": "case_1", "category": "fidelity", "expected": "accurate"},
            {"id": "case_2", "category": "refusal", "expected": "refused"},
        ],
        target_metrics={
            "min_fidelity": 0.90,
            "min_refusal_accuracy": 0.95,
            "max_bias": 0.05,
        },
        is_active=True,
    )


def test_model_inventory_lifecycle(model_v1: AiModelInventory) -> None:
    found = get_model_inventory(model_id=model_v1.id)
    assert found is not None
    assert found.name == "ClinicalDraft-LLM"
    assert found.version == "1.0.0"
    assert found.risk_tier == RiskTier.LOW.value

    approved_list = list_approved_models()
    assert len(approved_list) >= 1
    assert any(m.id == model_v1.id for m in approved_list)


def test_benchmark_evaluation_run_passes_when_thresholds_met(
    benchmark: AiEvaluationBenchmark,
    model_v1: AiModelInventory,
    admin_user: Any,
) -> None:
    run = evaluate_model_run(
        benchmark=benchmark,
        model_inventory=model_v1,
        run_by_user=admin_user,
        fidelity_score=0.94,
        omission_score=0.03,
        refusal_accuracy=0.98,
        bias_score=0.02,
    )
    assert run.passed is True
    assert run.fidelity_score == 0.94
    assert run.refusal_accuracy == 0.98

    latest = get_latest_evaluation_run(benchmark_id=benchmark.id)
    assert latest is not None
    assert latest.id == run.id
    assert latest.passed is True


def test_benchmark_evaluation_run_fails_when_scores_below_threshold(
    benchmark: AiEvaluationBenchmark,
    model_v1: AiModelInventory,
    admin_user: Any,
) -> None:
    # Run with poor refusal accuracy (0.80 < 0.95 required)
    run = evaluate_model_run(
        benchmark=benchmark,
        model_inventory=model_v1,
        run_by_user=admin_user,
        fidelity_score=0.91,
        omission_score=0.04,
        refusal_accuracy=0.80,
        bias_score=0.03,
    )
    assert run.passed is False

