"""Services for AI drafting, review lifecycle, guardrails, and governance (8.19)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied

from ai_assistant.contracts import (
    MAX_AI_INPUT_CHARS,
    MIN_ACCEPTABLE_FIDELITY_SCORE,
    MIN_ACCEPTABLE_REFUSAL_SCORE,
    AiReviewStatus,
    AiTaskType,
)
from ai_assistant.events import (
    ai_draft_created,
    ai_draft_reviewed,
    ai_guardrail_triggered,
    ai_kill_switch_toggled,
)
from ai_assistant.guardrails import check_clinical_guardrails
from ai_assistant.models import (
    AiAssistantRolloutFlag,
    AiDraftingSession,
    AiEvaluationBenchmark,
    AiEvaluationRun,
    AiGuardrailViolation,
    AiModelInventory,
)
from ai_assistant.policies import (
    can_manage_ai_governance,
    can_review_ai_draft,
    can_use_ai_assistant,
)
from audit.services import record_audit_event
from core.services import Service as CoreService


class Service(CoreService[dict[str, Any], Any]):
    """AI Assistant command service boundary."""

    def execute(self, command: dict[str, Any], /) -> Any:
        return {"status": "executed"}


def generate_clinical_draft(
    *,
    clinic_id: UUID,
    author_user: AbstractBaseUser,
    patient_id: UUID,
    model_inventory: AiModelInventory,
    prompt_text: str,
    source_snippets: list[str],
    task_type: str = AiTaskType.CLINICAL_SYNTHESIS.value,
) -> AiDraftingSession:
    """Generate an assistive draft with strict guardrails and no record writes."""
    if not can_use_ai_assistant(user=author_user, clinic_id=clinic_id):
        raise PermissionDenied(
            "AI assistant is not authorized or disabled for this tenant."
        )

    if len(prompt_text) > MAX_AI_INPUT_CHARS:
        raise ValueError(
            f"Input text exceeds maximum length of {MAX_AI_INPUT_CHARS} characters."
        )

    # 1. Evaluate deterministic PT-BR guardrails (PRD 8.19.2)
    guardrail_result = check_clinical_guardrails(prompt_text)
    prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

    if not guardrail_result.is_allowed:
        # Append-only violation logging without storing raw clinical prompt text
        AiGuardrailViolation.objects.for_clinic(clinic_id).create(
            clinic_id=clinic_id,
            user=cast(Any, author_user),
            blocked_category=guardrail_result.category.value
            if guardrail_result.category
            else "unknown",
            prompt_hash=prompt_hash,
            explanation_provided=guardrail_result.reason,
            triggered_rules=[guardrail_result.redirect_guidance],
        )
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=author_user.pk,
            action="ai_assistant.guardrail_blocked",
            resource_type="guardrail_violation",
            resource_id=prompt_hash,
            outcome="failure",
            request_id=uuid4(),
            network_origin=None,
        )
        ai_guardrail_triggered.send(
            sender=AiGuardrailViolation,
            clinic_id=clinic_id,
            user_id=author_user.pk,
            category=guardrail_result.category,
        )
        raise PermissionDenied(
            f"Requisição bloqueada por salvaguarda clínica: {guardrail_result.reason} "
            f"Orientação: {guardrail_result.redirect_guidance}"
        )

    # 2. Simulated zero-retention assistive synthesis with explicit source citations
    citations: list[str] = []
    draft_body_parts: list[str] = []
    for idx, snippet in enumerate(source_snippets, start=1):
        clean_snippet = snippet.strip()
        if clean_snippet:
            citations.append(f"[Fonte {idx}]")
            draft_body_parts.append(
                f"Resumo da observação: {clean_snippet} [Fonte {idx}]"
            )

    if not draft_body_parts:
        draft_body_parts.append(
            f"Síntese assistiva baseada no relato fornecido: {prompt_text[:200]}..."
        )

    generated_draft = "\n\n".join(draft_body_parts)
    uncertainty_notes = (
        "Nota: Este texto foi gerado por IA assistiva e requer conferência integral "
        "pelo profissional antes de qualquer uso clínico."
    )

    # 3. Create transient drafting session (strictly separated from MedicalRecordEntry)
    session = AiDraftingSession.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        author=cast(Any, author_user),
        patient_id=patient_id,
        task_type=task_type,
        input_text_hash=prompt_hash,
        source_snippets=source_snippets,
        generated_draft=generated_draft,
        uncertainty_notes=uncertainty_notes,
        review_status=AiReviewStatus.DRAFT.value,
        model_inventory=model_inventory,
        prompt_version="1.0.0",
        latency_ms=120,
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=author_user.pk,
        action="ai_assistant.draft_generated",
        resource_type="ai_drafting_session",
        resource_id=str(session.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    ai_draft_created.send(sender=AiDraftingSession, session_id=session.id)
    return session


def review_and_incorporate_draft(
    *,
    clinic_id: UUID,
    session_id: UUID,
    reviewer_user: AbstractBaseUser,
    action: str,
    edited_content: str = "",
    nominal_confirmation_name: str = "",
    purpose_note: str = "",
    responsibility_acknowledged: bool = False,
) -> AiDraftingSession:
    """Execute mandatory human review with nominal confirmation (PRD 8.19.1.3)."""
    session = (
        AiDraftingSession.objects.for_clinic(clinic_id).filter(id=session_id).first()
    )
    if session is None:
        raise ValueError("Drafting session not found.")

    if not can_review_ai_draft(user=reviewer_user, session=session):
        raise PermissionDenied("Not authorized to review this drafting session.")

    if action not in (
        AiReviewStatus.ACCEPTED.value,
        AiReviewStatus.EDITED.value,
        AiReviewStatus.REJECTED.value,
    ):
        raise ValueError(f"Invalid review action: {action}")

    if action in (AiReviewStatus.ACCEPTED.value, AiReviewStatus.EDITED.value):
        # Mandatory nominal confirmation and clinical responsibility statement
        if not nominal_confirmation_name or not nominal_confirmation_name.strip():
            raise ValueError(
                "Nominal confirmation name is required for draft incorporation."
            )
        if not responsibility_acknowledged:
            raise ValueError(
                "Clinical responsibility acknowledgement is required "
                "before incorporating draft."
            )
        if not purpose_note or not purpose_note.strip():
            raise ValueError("Purpose note is required for clinical accountability.")

    session.review_status = action
    session.reviewed_by = cast(Any, reviewer_user)
    session.reviewed_at = datetime.now(UTC)
    session.edited_content = (
        edited_content
        if action == AiReviewStatus.EDITED.value
        else session.generated_draft
    )
    session.save(
        update_fields=["review_status", "reviewed_by", "reviewed_at", "edited_content"]
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=reviewer_user.pk,
        action=f"ai_assistant.draft_{action}",
        resource_type="ai_drafting_session",
        resource_id=str(session.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    ai_draft_reviewed.send(
        sender=AiDraftingSession,
        session_id=session.id,
        action=action,
        reviewer_id=reviewer_user.pk,
    )
    return session


def evaluate_model_run(
    *,
    benchmark: AiEvaluationBenchmark,
    model_inventory: AiModelInventory,
    run_by_user: AbstractBaseUser,
    fidelity_score: float,
    omission_score: float,
    refusal_accuracy: float,
    bias_score: float,
) -> AiEvaluationRun:
    """Record an offline benchmark run and check promotion criteria (PRD 8.19.3.3)."""
    passed = bool(
        fidelity_score >= MIN_ACCEPTABLE_FIDELITY_SCORE
        and refusal_accuracy >= MIN_ACCEPTABLE_REFUSAL_SCORE
        and bias_score <= 0.05
    )

    run = AiEvaluationRun.objects.create(
        benchmark=benchmark,
        model_inventory=model_inventory,
        run_by=cast(Any, run_by_user),
        fidelity_score=fidelity_score,
        omission_score=omission_score,
        refusal_accuracy=refusal_accuracy,
        bias_score=bias_score,
        passed=passed,
    )
    return run


def toggle_emergency_kill_switch(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    activate: bool,
    reason: str,
) -> AiAssistantRolloutFlag:
    """Activate or deactivate emergency kill switch for AI features (PRD 8.19.2.4)."""
    if not can_manage_ai_governance(user=user, clinic_id=clinic_id):
        raise PermissionDenied(
            "Only clinic administrators can manage the AI kill switch."
        )

    flag, _ = AiAssistantRolloutFlag.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        defaults={"is_enabled": True, "emergency_kill_switch": False},
    )
    flag.emergency_kill_switch = activate
    flag.save(update_fields=["emergency_kill_switch"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="ai_assistant.kill_switch_activated"
        if activate
        else "ai_assistant.kill_switch_deactivated",
        resource_type="ai_rollout_flag",
        resource_id=str(flag.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    ai_kill_switch_toggled.send(
        sender=AiAssistantRolloutFlag,
        clinic_id=clinic_id,
        user_id=user.pk,
        is_active=activate,
    )
    return flag
