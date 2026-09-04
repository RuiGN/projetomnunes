"""Side-effect-free selectors for AI assistant sessions and governance."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ai_assistant.models import (
    AiAssistantRolloutFlag,
    AiDraftingSession,
    AiEvaluationRun,
    AiGuardrailViolation,
    AiModelInventory,
)
from core.selectors import Selector as CoreSelector


class Selector(CoreSelector[dict[str, Any], Any]):
    """AI assistant query boundary."""

    def select(self, query: dict[str, Any], /) -> Any:
        clinic_id = query.get("clinic_id")
        if not clinic_id:
            raise ValueError("clinic_id is required for AI assistant queries.")
        return AiDraftingSession.objects.for_clinic(clinic_id).all()


def get_drafting_session(
    *, clinic_id: UUID, session_id: UUID
) -> AiDraftingSession | None:
    """Retrieve one drafting session ensuring tenant isolation."""
    return (
        AiDraftingSession.objects.for_clinic(clinic_id)
        .filter(id=session_id)
        .first()
    )


def list_drafting_sessions_for_patient(
    *, clinic_id: UUID, patient_id: UUID
) -> list[AiDraftingSession]:
    """List drafting sessions for a patient."""
    return list(
        AiDraftingSession.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_id)
        .order_by("-created_at")
    )


def get_model_inventory(*, model_id: UUID) -> AiModelInventory | None:
    """Retrieve an approved model from the global inventory."""
    return AiModelInventory.objects.filter(id=model_id, is_active=True).first()


def list_approved_models() -> list[AiModelInventory]:
    """List all currently active and approved models."""
    return list(AiModelInventory.objects.filter(is_active=True).order_by("name"))


def get_rollout_flag(*, clinic_id: UUID) -> AiAssistantRolloutFlag | None:
    """Retrieve tenant rollout and kill switch status."""
    return AiAssistantRolloutFlag.objects.for_clinic(clinic_id).first()


def get_guardrail_violations_summary(*, clinic_id: UUID) -> list[dict[str, Any]]:
    """Return an aggregated audit summary of high-risk violations without raw text."""
    violations = (
        AiGuardrailViolation.objects.for_clinic(clinic_id)
        .order_by("-created_at")[:50]
    )
    return [
        {
            "id": v.id,
            "category": v.blocked_category,
            "prompt_hash": v.prompt_hash,
            "explanation": v.explanation_provided,
            "created_at": v.created_at.isoformat(),
        }
        for v in violations
    ]


def get_latest_evaluation_run(*, benchmark_id: UUID) -> AiEvaluationRun | None:
    """Get the latest evaluation run for a benchmark."""
    return (
        AiEvaluationRun.objects.filter(benchmark_id=benchmark_id)
        .order_by("-created_at")
        .first()
    )

