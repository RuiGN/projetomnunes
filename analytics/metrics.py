"""Documented metric catalog and shared dashboard value objects.

Every metric below records its formula, granularity, population, period and
limitations, satisfying 8.9.1.1 and 8.9.5.1 without persisting a schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One documented MVP metric."""

    key: str
    label_pt: str
    formula: str
    granularity: str
    population: str
    period: str
    limitations: str


METRIC_CATALOG: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="checkin_frequency",
        label_pt="Frequência de check-ins",
        formula="contagem de check-ins submetidos no período",
        granularity="por paciente (autorrelato)",
        population="paciente (próprios) / terapeuta (compartilhados Verde)",
        period="período selecionado",
        limitations="autorrelato; ausência de registro não indica estado clínico",
    ),
    MetricDefinition(
        key="mood_distribution",
        label_pt="Distribuição de humor",
        formula="histograma de humor (1–5) dos registros de diário no período",
        granularity="por paciente",
        population="paciente (próprios)",
        period="período selecionado",
        limitations="descritivo; não é diagnóstico nem causalidade",
    ),
    MetricDefinition(
        key="active_goals",
        label_pt="Metas em andamento",
        formula="contagem de metas com status ativo",
        granularity="por paciente",
        population="paciente (próprias)",
        period="instantâneo",
        limitations="não mede resultado terapêutico",
    ),
    MetricDefinition(
        key="completed_exercises",
        label_pt="Exercícios concluídos",
        formula="contagem de execuções concluídas no período",
        granularity="por paciente",
        population="paciente (próprias)",
        period="período selecionado",
        limitations="conclusão não implica adesão plena",
    ),
    MetricDefinition(
        key="upcoming_appointments",
        label_pt="Próximas consultas",
        formula="contagem de consultas futuras confirmadas/solicitadas",
        granularity="por paciente / por terapeuta",
        population="paciente (próprias) / terapeuta (vinculadas)",
        period="do momento atual em diante",
        limitations="agenda é operacional, não clínica",
    ),
    MetricDefinition(
        key="active_patients",
        label_pt="Pacientes ativos",
        formula="contagem de pacientes com vínculo ativo",
        granularity="por terapeuta / por clínica",
        population="terapeuta (vinculados) / clínica (agregado)",
        period="instantâneo",
        limitations="vínculo ativo é fato administrativo",
    ),
    MetricDefinition(
        key="pending_triage",
        label_pt="Triagem pendente",
        formula="contagem de itens de triagem humana pendentes",
        granularity="por terapeuta",
        population="pacientes vinculados",
        period="instantâneo",
        limitations="sinalização configurada, nunca diagnóstico automático",
    ),
    MetricDefinition(
        key="schedule_occupancy",
        label_pt="Ocupação da agenda",
        formula="(confirmadas + realizadas) / total de consultas no período",
        granularity="por clínica / unidade / profissional",
        population="agregado acima do limiar de anonimização",
        period="período selecionado",
        limitations="depende do registro de presença",
    ),
    MetricDefinition(
        key="no_show_rate",
        label_pt="Taxa de faltas",
        formula="faltas / (realizadas + faltas) no período",
        granularity="por clínica",
        population="agregado acima do limiar de anonimização",
        period="período selecionado",
        limitations="falta é registro administrativo, não julgamento",
    ),
    MetricDefinition(
        key="cancellations",
        label_pt="Cancelamentos",
        formula="contagem de consultas canceladas no período",
        granularity="por clínica",
        population="agregado acima do limiar de anonimização",
        period="período selecionado",
        limitations="não distingue motivo",
    ),
)


@dataclass(frozen=True, slots=True)
class PatientDashboardData:
    """Aggregated patient-owned metrics for one period."""

    period_start: date
    period_end: date
    checkin_count: int
    mood_distribution: tuple[int, ...]  # counts for moods 1..5
    active_goals: int
    completed_exercises: int
    upcoming_appointments: int

    @property
    def has_data(self) -> bool:
        return self.checkin_count > 0 or sum(self.mood_distribution) > 0


@dataclass(frozen=True, slots=True)
class PatientActivityRow:
    """One linked patient's shareable check-in count for the therapist view."""

    patient_profile_id: object
    full_name: str
    checkin_count: int


@dataclass(frozen=True, slots=True)
class TriageRow:
    """One pending human-review item, minimized for the therapist dashboard."""

    reason: str
    rule_name: str
    monitoring_window: str
    patient_name: str


@dataclass(frozen=True, slots=True)
class TherapistDashboardData:
    """Authorized metrics for one therapist's linked patients."""

    period_start: date
    period_end: date
    active_patients: int
    pending_triage: int
    upcoming_appointments: int
    triage_items: tuple[TriageRow, ...]
    activity_rows: tuple[PatientActivityRow, ...]


@dataclass(frozen=True, slots=True)
class GroupedCountRow:
    """One anonymized grouping with suppressed small cells."""

    label: str
    count: int | None  # None means suppressed below the aggregation threshold


@dataclass(frozen=True, slots=True)
class ClinicOperationalData:
    """Anonymized operational metrics for the clinic panel."""

    period_start: date
    period_end: date
    total_appointments: int
    confirmed: int
    completed: int
    no_show: int
    canceled: int
    requested: int
    occupancy_rate: float | None
    no_show_rate: float | None
    active_patients: int | None
    by_unit: tuple[GroupedCountRow, ...]
    by_professional: tuple[GroupedCountRow, ...]
    last_updated: datetime
