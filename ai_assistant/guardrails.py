"""Deterministic guardrails and high-risk intent exclusion (PRD 8.19.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_assistant.contracts import GuardrailCategory


@dataclass(frozen=True)
class GuardrailCheckResult:
    """Result of evaluating a prompt against deterministic clinical guardrails."""

    is_allowed: bool
    category: GuardrailCategory | None
    reason: str
    redirect_guidance: str


_DIAGNOSIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(diagnosticar|diagnóstico|hipótese\s+diagnóstica)\b", re.IGNORECASE),
    re.compile(r"\bCID[-\s]?(10|11)\b", re.IGNORECASE),
    re.compile(r"\b(o\s+paciente\s+tem|apresenta\s+o\s+transtorno)\b", re.IGNORECASE),
)

_PRESCRIPTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(prescrever|receitar|prescrição)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(mg|ml|gotas|comprimidos?)\b", re.IGNORECASE),
    re.compile(
        r"\b(posologia|dosagem\s+de|tomar\s+de\s+\d+\s+em\s+\d+)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(fluoxetina|sertralina|clonazepam|escitalopram|venlafaxina|quetiapina|zolpidem|risperidona)\b",
        re.IGNORECASE,
    ),
)

_TEST_INTERPRETATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(interpretar|laudar|laudo\s+do\s+exame)\b", re.IGNORECASE),
    re.compile(
        r"\b(hemograma|ressonância|tomografia|eletroencefalograma)\s+(indica|mostra|comprova)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(escala\s+de\s+beck|phq[-\s]?9|gad[-\s]?7)\s+(indica|diagnostica|aponta\s+gravidade)\b",
        re.IGNORECASE,
    ),
)

_AUTONOMOUS_TRIAGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(triagem\s+automática|classificar\s+como\s+emergência)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(escore|score)\s+de\s+risco\s+(suicida|de\s+morte|clínico)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(priorizar|definir\s+prioridade\s+de\s+atendimento)\b", re.IGNORECASE
    ),
)

_TREATMENT_DECISION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(suspender|interromper|alterar)\s+(o\s+tratamento|a\s+medicação)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(indicar|decidir\s+por)\s+(internação|cirurgia|terapia\s+eletroconvulsiva)\b",
        re.IGNORECASE,
    ),
)

_ADVERSARIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(ignore\s+(as\s+)?instruções(\s+anteriores)?)\b", re.IGNORECASE),
    re.compile(
        r"\b(modo\s+desenvolvedor|modo\s+médico\s+ativado|jailbreak|dan\s+mode)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(finja\s+que\s+você\s+é\s+(um\s+)?médico)\b", re.IGNORECASE),
    re.compile(
        r"\b(como\s+burlar|desativar\s+filtros\s+de\s+segurança)\b", re.IGNORECASE
    ),
)

_DISCIPLINARY_OR_INSURANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(demissão|demitir|justa\s+causa|disciplinar)\b", re.IGNORECASE),
    re.compile(
        r"\b(seguradora|seguro|cobertura\s+do\s+plano|negar\s+cobertura)\b",
        re.IGNORECASE,
    ),
)


def check_clinical_guardrails(prompt: str) -> GuardrailCheckResult:
    """Evaluate an input prompt against high-risk exclusion rules.

    Under PRD 8.19.2, AI cannot perform diagnosis, prescription, test interpretation,
    autonomous triage, risk scoring, treatment decisions, or disciplinary evaluation.
    """
    cleaned = prompt.strip()
    if not cleaned:
        return GuardrailCheckResult(
            is_allowed=False,
            category=None,
            reason="Prompt vazio ou inválido.",
            redirect_guidance="Forneça o texto de observação para formatação.",
        )

    # 1. Adversarial attempts
    for pattern in _ADVERSARIAL_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.ADVERSARIAL_JAILBREAK,
                reason="Tentativa de desvio das instruções ou salvaguardas.",
                redirect_guidance="Comandos de bypass de segurança não são permitidos.",
            )

    # 2. Diagnosis exclusion
    for pattern in _DIAGNOSIS_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.DIAGNOSIS,
                reason="Diagnóstico é atribuição exclusiva de profissional habilitado.",
                redirect_guidance="Consulte diretamente o profissional de saúde.",
            )

    # 3. Prescription & dosage exclusion
    for pattern in _PRESCRIPTION_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.PRESCRIPTION,
                reason="Prescrição de medicamentos/dosagens é vedada para a IA.",
                redirect_guidance="A conduta medicamentosa deve ser feita por médico.",
            )

    # 4. Lab / scale interpretation exclusion
    for pattern in _TEST_INTERPRETATION_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.TEST_INTERPRETATION,
                reason="Interpretação de laudos exige julgamento clínico humano.",
                redirect_guidance="Encaminhe os resultados ao profissional.",
            )

    # 5. Autonomous triage & risk score exclusion
    for pattern in _AUTONOMOUS_TRIAGE_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.AUTONOMOUS_TRIAGE,
                reason="Triagem autônoma e escore de risco automatizado são vedados.",
                redirect_guidance="Em urgência, acione os serviços de emergência.",
            )

    # 6. Treatment decision exclusion
    for pattern in _TREATMENT_DECISION_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.TREATMENT_DECISION,
                reason="Decisões de conduta terapêutica não são automatizadas.",
                redirect_guidance="A definição do plano compete ao profissional.",
            )

    # 7. Disciplinary or insurance exclusion
    for pattern in _DISCIPLINARY_OR_INSURANCE_PATTERNS:
        if pattern.search(cleaned):
            return GuardrailCheckResult(
                is_allowed=False,
                category=GuardrailCategory.DISCIPLINARY_OR_INSURANCE,
                reason="Uso da IA para fins disciplinares/securitários é proibido.",
                redirect_guidance="A plataforma destina-se ao suporte assistencial.",
            )

    return GuardrailCheckResult(
        is_allowed=True,
        category=None,
        reason="",
        redirect_guidance="",
    )
