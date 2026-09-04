"""Models for AI governance, drafting sessions, violations and benchmarks."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from django.conf import settings
from django.db import models

from ai_assistant.contracts import (
    AiReviewStatus,
    AiTaskType,
    GuardrailCategory,
    RiskTier,
)
from core.persistence import UUIDTimestampedModel

_ModelT = TypeVar("_ModelT", bound=models.Model)


class AiQuerySet(models.QuerySet[_ModelT]):
    """Tenant-scoped query set for AI Assistant models."""

    def for_clinic(self: AiQuerySet[_ModelT], clinic_id: UUID) -> AiQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class AiTenantManager(models.Manager[_ModelT]):
    """Tenant-safe manager requiring an explicit clinic scope."""

    def get_queryset(self) -> AiQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return AiQuerySet(self.model, using=self._db)
        raise RuntimeError("AI Assistant queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: AiTenantManager[_ModelT], clinic_id: UUID
    ) -> AiQuerySet[_ModelT]:
        return AiQuerySet(self.model, using=self._db).for_clinic(clinic_id)

    def create(self, **kwargs: Any) -> _ModelT:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return super().create(**kwargs)
        clinic_id = kwargs.get("clinic_id")
        if not clinic_id and "clinic" in kwargs:
            clinic = kwargs["clinic"]
            clinic_id = getattr(clinic, "id", clinic)
        if clinic_id:
            return self.for_clinic(clinic_id).create(**kwargs)
        return AiQuerySet(self.model, using=self._db).create(**kwargs)


class InfrastructureAiManager(models.Manager[_ModelT]):
    """Unrestricted AI Assistant manager for internal administration and migrations."""

    def get_queryset(self) -> AiQuerySet[_ModelT]:
        return AiQuerySet(self.model, using=self._db)


class AiModelInventory(UUIDTimestampedModel):
    """Inventory of approved foundation models and vendors (PRD 8.19.3.1)."""

    name = models.CharField(max_length=128)
    version = models.CharField(max_length=64)
    provider = models.CharField(max_length=128)
    processing_region = models.CharField(max_length=64, default="sa-east-1")
    legal_basis = models.CharField(
        max_length=128, default="Legítimo Interesse / Execução de Contrato"
    )
    risk_tier = models.CharField(
        max_length=32,
        choices=[(rt.value, rt.name) for rt in RiskTier],
        default=RiskTier.LOW.value,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_ai_models",
        null=True,
        blank=True,
    )
    reevaluation_date = models.DateField()
    is_active = models.BooleanField(default=True)

    objects = InfrastructureAiManager["AiModelInventory"]()
    infrastructure_objects = InfrastructureAiManager["AiModelInventory"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        unique_together = ("name", "version")


class AiDraftingSession(UUIDTimestampedModel):
    """Drafting session with side-by-side sources and human review (PRD 8.19.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="ai_drafting_sessions"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_drafting_sessions",
    )
    patient_id = models.UUIDField(db_index=True)
    task_type = models.CharField(
        max_length=48,
        choices=[(t.value, t.name) for t in AiTaskType],
        default=AiTaskType.CLINICAL_SYNTHESIS.value,
    )
    input_text_hash = models.CharField(max_length=64)
    source_snippets = models.JSONField(default=list)
    generated_draft = models.TextField()
    uncertainty_notes = models.TextField(blank=True)
    review_status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in AiReviewStatus],
        default=AiReviewStatus.DRAFT.value,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_ai_drafts",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    edited_content = models.TextField(blank=True)
    model_inventory = models.ForeignKey(
        AiModelInventory,
        on_delete=models.PROTECT,
        related_name="drafting_sessions",
    )
    prompt_version = models.CharField(max_length=32, default="1.0.0")
    latency_ms = models.PositiveIntegerField(default=0)

    objects = AiTenantManager["AiDraftingSession"]()
    infrastructure_objects = InfrastructureAiManager["AiDraftingSession"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"


class AiGuardrailViolation(UUIDTimestampedModel):
    """Append-only audit record of attempted high-risk clinical tasks (PRD 8.19.2.4)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ai_guardrail_violations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_guardrail_violations",
    )
    blocked_category = models.CharField(
        max_length=48,
        choices=[(c.value, c.name) for c in GuardrailCategory],
    )
    prompt_hash = models.CharField(max_length=64)
    explanation_provided = models.TextField()
    triggered_rules = models.JSONField(default=list)

    objects = AiTenantManager["AiGuardrailViolation"]()
    infrastructure_objects = InfrastructureAiManager["AiGuardrailViolation"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"


class AiEvaluationBenchmark(UUIDTimestampedModel):
    """Benchmark dataset for evaluating model fidelity and bias (PRD 8.19.3.2)."""

    name = models.CharField(max_length=128, unique=True)
    dataset_version = models.CharField(max_length=32)
    cases_json = models.JSONField(default=list)
    target_metrics = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    objects = InfrastructureAiManager["AiEvaluationBenchmark"]()
    infrastructure_objects = InfrastructureAiManager["AiEvaluationBenchmark"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"


class AiEvaluationRun(UUIDTimestampedModel):
    """Evaluation benchmark run results against an approved model (PRD 8.19.3.3)."""

    benchmark = models.ForeignKey(
        AiEvaluationBenchmark, on_delete=models.CASCADE, related_name="runs"
    )
    model_inventory = models.ForeignKey(
        AiModelInventory, on_delete=models.CASCADE, related_name="evaluation_runs"
    )
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_evaluation_runs",
    )
    fidelity_score = models.FloatField()
    omission_score = models.FloatField()
    refusal_accuracy = models.FloatField()
    bias_score = models.FloatField()
    passed = models.BooleanField(default=False)

    objects = InfrastructureAiManager["AiEvaluationRun"]()
    infrastructure_objects = InfrastructureAiManager["AiEvaluationRun"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"


class AiAssistantRolloutFlag(UUIDTimestampedModel):
    """Rollout flag and emergency kill switch for AI features (PRD 8.19.2.4)."""

    clinic = models.OneToOneField(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="ai_rollout_flag"
    )
    is_enabled = models.BooleanField(default=False)
    emergency_kill_switch = models.BooleanField(default=False)
    max_context_chars = models.PositiveIntegerField(default=4000)

    objects = AiTenantManager["AiAssistantRolloutFlag"]()
    infrastructure_objects = InfrastructureAiManager["AiAssistantRolloutFlag"]()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
