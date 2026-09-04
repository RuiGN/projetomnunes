"""Semantic metric dictionary for clinical and operational indicators (8.19.4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MetricCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class MetricCategory(StrEnum):
    CLINICAL_OPERATIONS = "clinical_operations"
    CARE_QUALITY = "care_quality"
    PATIENT_ENGAGEMENT = "patient_engagement"
    COMPLIANCE = "compliance"


@dataclass(frozen=True)
class MetricDefinition:
    """Explicit dictionary definition ensuring governed interpretation of metrics."""

    id: str
    name: str
    category: MetricCategory
    description: str
    population: str
    denominator: str
    cadence: MetricCadence
    owner_role: str
    allowed_interpretation: str
    small_cell_threshold: int = 5


# Standard registry of pre-approved metric definitions
APPROVED_METRICS_REGISTRY: dict[str, MetricDefinition] = {
    "active_patients_count": MetricDefinition(
        id="active_patients_count",
        name="Total de Pacientes Ativos",
        category=MetricCategory.CLINICAL_OPERATIONS,
        description="Contagem de pacientes com vínculo ativo na clínica.",
        population="Todos os pacientes cadastrados na clínica",
        denominator="N/A (contagem absoluta)",
        cadence=MetricCadence.MONTHLY,
        owner_role="clinical_director",
        allowed_interpretation="Dimensionamento e planejamento de equipe assistencial.",
        small_cell_threshold=5,
    ),
    "session_attendance_rate": MetricDefinition(
        id="session_attendance_rate",
        name="Taxa de Comparecimento às Sessões",
        category=MetricCategory.PATIENT_ENGAGEMENT,
        description="Percentual de sessões realizadas sobre o total agendado.",
        population="Agendamentos confirmados no período",
        denominator="Total de sessões confirmadas no período",
        cadence=MetricCadence.WEEKLY,
        owner_role="therapist",
        allowed_interpretation="Avaliação de assiduidade geral sem fins disciplinares.",
        small_cell_threshold=5,
    ),
    "routine_adherence_rate": MetricDefinition(
        id="routine_adherence_rate",
        name="Taxa de Adesão às Rotinas de Cuidado",
        category=MetricCategory.CARE_QUALITY,
        description="Percentual de checagens de rotina concluídas pelos pacientes.",
        population="Itens de rotina prescritos no plano de cuidado ativo",
        denominator="Total de rotinas programadas no período",
        cadence=MetricCadence.WEEKLY,
        owner_role="therapist",
        allowed_interpretation="Acompanhamento da evolução terapêutica agregada.",
        small_cell_threshold=5,
    ),
    "checkin_completion_rate": MetricDefinition(
        id="checkin_completion_rate",
        name="Taxa de Conclusão de Check-ins Diários",
        category=MetricCategory.PATIENT_ENGAGEMENT,
        description="Percentual de check-ins de bem-estar preenchidos.",
        population="Pacientes com monitoramento ativo no diário",
        denominator="Dias ativos no período",
        cadence=MetricCadence.DAILY,
        owner_role="therapist",
        allowed_interpretation="Sinalização de engajamento do paciente.",
        small_cell_threshold=5,
    ),
}


def get_metric_definition(metric_id: str) -> MetricDefinition | None:
    """Retrieve an approved metric definition by its identifier."""
    return APPROVED_METRICS_REGISTRY.get(metric_id)
