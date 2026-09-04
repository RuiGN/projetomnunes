"""Contracts, enums and limits for AI assistant and clinical guardrails."""

from enum import StrEnum

# Input and context limits to enforce data minimization
MAX_AI_INPUT_CHARS: int = 4000
MIN_ACCEPTABLE_FIDELITY_SCORE: float = 0.90
MIN_ACCEPTABLE_REFUSAL_SCORE: float = 0.95


class AiTaskType(StrEnum):
    """Allowed low-risk assistive drafting task types (8.19.1)."""

    CLINICAL_SYNTHESIS = "clinical_synthesis"
    TEXT_FORMATTING = "text_formatting"
    OBSERVATION_SUMMARIZATION = "observation_summarization"


class AiReviewStatus(StrEnum):
    """Mandatory human-in-the-loop review lifecycle (8.19.1.2)."""

    DRAFT = "draft"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class GuardrailCategory(StrEnum):
    """Prohibited high-risk categories under PRD 8.19.2."""

    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    TEST_INTERPRETATION = "test_interpretation"
    AUTONOMOUS_TRIAGE = "autonomous_triage"
    RISK_SCORE = "risk_score"
    TREATMENT_DECISION = "treatment_decision"
    UNVALIDATED_ALERT = "unvalidated_alert"
    DISCIPLINARY_OR_INSURANCE = "disciplinary_or_insurance"
    ADVERSARIAL_JAILBREAK = "adversarial_jailbreak"


class RiskTier(StrEnum):
    """Risk tier mapping for AI model governance (8.19.3.1)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"


class EvaluationDimension(StrEnum):
    """Dimensions evaluated in offline de-identified benchmarks (8.19.3.2)."""

    FIDELITY = "fidelity"
    OMISSION = "omission"
    NON_STIGMATIZING = "non_stigmatizing"
    SAFETY = "safety"
    REFUSAL_ACCURACY = "refusal_accuracy"

