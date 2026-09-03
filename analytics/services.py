"""Authorized metric aggregation and MVP report generation."""

from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.selectors import active_clinics_for_actor
from core.services import Service as Service
from goals.selectors import patient_exercise_executions, patient_goals
from journal.selectors import (
    patient_checkins,
    patient_journal_entries,
    pending_triage_for_therapist,
    therapist_visible_checkins,
)
from people.selectors import (
    active_patient_profile_count,
    linked_patients_for_therapist,
)
from scheduling.selectors import appointments_visible_to

from .events import report_downloaded, report_generated
from .metrics import (
    ClinicOperationalData,
    GroupedCountRow,
    PatientActivityRow,
    PatientDashboardData,
    TherapistDashboardData,
    TriageRow,
)
from .models import Report, ReportKind, ReportStatus

__all__ = [
    "Service",
    "DEFAULT_ANONYMIZATION_THRESHOLD",
    "ACTIVE_APPOINTMENT_STATUSES",
    "authorize_report_download",
    "clinic_operational_metrics",
    "generate_individual_report",
    "generate_operational_report",
    "patient_dashboard_metrics",
    "therapist_dashboard_metrics",
]

DEFAULT_ANONYMIZATION_THRESHOLD = 5
ACTIVE_APPOINTMENT_STATUSES = frozenset(
    {"requested", "confirmed", "reschedule_requested"}
)
REPORT_TTL_HOURS = 24


def _bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    if period_end < period_start:
        raise ValidationError("O período final deve ser igual ou posterior ao inicial.")
    start = timezone.make_aware(datetime.combine(period_start, time.min))
    end = timezone.make_aware(datetime.combine(period_end, time.max))
    return start, end


def _clinic_name(clinic_id: UUID, actor: AbstractBaseUser) -> str:
    clinic = next(
        (c for c in active_clinics_for_actor(actor) if c.pk == clinic_id),
        None,
    )
    return clinic.name if clinic is not None else "Clínica"


# ---------------------------------------------------------------------------
# Patient dashboard (8.9.2)
# ---------------------------------------------------------------------------


def patient_dashboard_metrics(
    *, clinic_id: UUID, actor: AbstractBaseUser, period_start: date, period_end: date
) -> PatientDashboardData:
    """Aggregate only the patient's own data for one period."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    start, end = _bounds(period_start, period_end)

    entries = [
        entry
        for entry in patient_journal_entries(clinic_id=clinic_id, actor=actor)
        if start <= entry.created_at <= end
    ]
    checkins = [
        checkin
        for checkin in patient_checkins(clinic_id=clinic_id, actor=actor, since=start)
        if checkin.submitted_at is not None and checkin.submitted_at <= end
    ]
    active_goals = sum(
        1
        for goal in patient_goals(clinic_id=clinic_id, actor=actor)
        if goal.status == "active"
    )
    executions = patient_exercise_executions(
        clinic_id=clinic_id, actor=actor, completed_only=True
    )
    completed_exercises = sum(
        1
        for execution in executions
        if execution.completed_at is not None and start <= execution.completed_at <= end
    )
    upcoming = appointments_visible_to(
        clinic_id=clinic_id, actor=actor, from_at=timezone.now()
    )
    upcoming_count = sum(
        1
        for appointment in upcoming
        if appointment.status in ACTIVE_APPOINTMENT_STATUSES
    )

    mood_distribution = [0, 0, 0, 0, 0]
    for entry in entries:
        if 1 <= entry.mood <= 5:
            mood_distribution[entry.mood - 1] += 1

    return PatientDashboardData(
        period_start=period_start,
        period_end=period_end,
        checkin_count=len(checkins),
        mood_distribution=tuple(mood_distribution),
        active_goals=active_goals,
        completed_exercises=completed_exercises,
        upcoming_appointments=upcoming_count,
    )


# ---------------------------------------------------------------------------
# Therapist dashboard (8.9.3)
# ---------------------------------------------------------------------------


def therapist_dashboard_metrics(
    *, clinic_id: UUID, actor: AbstractBaseUser, period_start: date, period_end: date
) -> TherapistDashboardData:
    """Aggregate only linked and authorized patient data for one therapist."""
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=today
    ):
        raise PermissionDenied
    start, end = _bounds(period_start, period_end)

    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=actor.pk, on_date=today
    )
    profile_names = {row.patient_profile_id: row.full_name for row in linked}

    triage = pending_triage_for_therapist(clinic_id=clinic_id, therapist_id=actor.pk)
    triage_rows = tuple(
        TriageRow(
            reason=item.reason,
            rule_name=item.rule.name,
            monitoring_window=item.rule.get_monitoring_window_display(),
            patient_name=profile_names.get(item.patient_profile_id, "Paciente"),
        )
        for item in triage
    )

    activity: dict[UUID, int] = {}
    for checkin in therapist_visible_checkins(
        clinic_id=clinic_id, therapist_id=actor.pk, since=start
    ):
        if checkin.submitted_at is not None and checkin.submitted_at <= end:
            activity[checkin.patient_profile_id] = (
                activity.get(checkin.patient_profile_id, 0) + 1
            )
    activity_rows = tuple(
        PatientActivityRow(
            patient_profile_id=profile_id,
            full_name=profile_names.get(profile_id, "Paciente"),
            checkin_count=count,
        )
        for profile_id, count in sorted(activity.items())
    )

    upcoming = appointments_visible_to(
        clinic_id=clinic_id, actor=actor, from_at=timezone.now()
    )
    upcoming_count = sum(
        1
        for appointment in upcoming
        if appointment.status in ACTIVE_APPOINTMENT_STATUSES
    )

    return TherapistDashboardData(
        period_start=period_start,
        period_end=period_end,
        active_patients=len(linked),
        pending_triage=len(triage),
        upcoming_appointments=upcoming_count,
        triage_items=triage_rows,
        activity_rows=activity_rows,
    )


# ---------------------------------------------------------------------------
# Clinic operational panel (8.9.4)
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 1)


def clinic_operational_metrics(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
    min_threshold: int = DEFAULT_ANONYMIZATION_THRESHOLD,
) -> ClinicOperationalData:
    """Aggregate anonymized operational metrics for one clinic."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    start, end = _bounds(period_start, period_end)

    appointments = appointments_visible_to(
        clinic_id=clinic_id, actor=actor, from_at=start, to_at=end
    )
    total = len(appointments)
    counts = {
        "confirmed": 0,
        "completed": 0,
        "no_show": 0,
        "canceled": 0,
        "requested": 0,
    }
    by_unit: dict[str, int] = {}
    by_professional: dict[str, int] = {}
    for appointment in appointments:
        if appointment.status in counts:
            counts[appointment.status] += 1
        unit_label = appointment.unit.name if appointment.unit_id else "Sem unidade"
        by_unit[unit_label] = by_unit.get(unit_label, 0) + 1
        professional_label = appointment.professional.get_full_name() or "Profissional"
        by_professional[professional_label] = (
            by_professional.get(professional_label, 0) + 1
        )

    confirmed = counts["confirmed"]
    completed = counts["completed"]
    no_show = counts["no_show"]
    occupancy = _rate(confirmed + completed, total)
    no_show_rate = _rate(no_show, completed + no_show)

    active_patients = active_patient_profile_count(
        clinic_id=clinic_id, on_date=timezone.localdate()
    )

    return ClinicOperationalData(
        period_start=period_start,
        period_end=period_end,
        total_appointments=total,
        confirmed=confirmed,
        completed=completed,
        no_show=no_show,
        canceled=counts["canceled"],
        requested=counts["requested"],
        occupancy_rate=occupancy,
        no_show_rate=no_show_rate,
        active_patients=active_patients if active_patients >= min_threshold else None,
        by_unit=tuple(
            GroupedCountRow(
                label=label, count=count if count >= min_threshold else None
            )
            for label, count in sorted(by_unit.items())
        ),
        by_professional=tuple(
            GroupedCountRow(
                label=label, count=count if count >= min_threshold else None
            )
            for label, count in sorted(by_professional.items())
        ),
        last_updated=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Reports (8.9.5)
# ---------------------------------------------------------------------------


def _individual_report_text(
    *, data: PatientDashboardData, clinic_name: str, generated_at: datetime
) -> str:
    lines = [
        f"Relatório individual — {clinic_name}",
        f"Período: {data.period_start:%d/%m/%Y} a {data.period_end:%d/%m/%Y}",
        f"Gerado em: {generated_at:%d/%m/%Y %H:%M}",
        "",
        f"Check-ins no período: {data.checkin_count}",
        "Distribuição de humor (registros de diário):",
        f"  1 Muito mal: {data.mood_distribution[0]}",
        f"  2 Mal: {data.mood_distribution[1]}",
        f"  3 Neutro: {data.mood_distribution[2]}",
        f"  4 Bem: {data.mood_distribution[3]}",
        f"  5 Muito bem: {data.mood_distribution[4]}",
        f"Metas em andamento: {data.active_goals}",
        f"Exercícios concluídos: {data.completed_exercises}",
        f"Próximas consultas: {data.upcoming_appointments}",
        "",
        "Este relatório descreve autorrelatos e não constitui diagnóstico, "
        "recomendação clínica ou relação de causalidade.",
    ]
    return "\n".join(lines)


def _operational_report_text(
    *, data: ClinicOperationalData, clinic_name: str, generated_at: datetime
) -> str:
    lines = [
        f"Relatório operacional — {clinic_name}",
        f"Período: {data.period_start:%d/%m/%Y} a {data.period_end:%d/%m/%Y}",
        f"Gerado em: {generated_at:%d/%m/%Y %H:%M}",
        "",
        f"Consultas no período: {data.total_appointments}",
        f"Confirmadas: {data.confirmed}",
        f"Realizadas: {data.completed}",
        f"Faltas: {data.no_show}",
        f"Canceladas: {data.canceled}",
        f"Ocupação da agenda: "
        f"{data.occupancy_rate if data.occupancy_rate is not None else '—'}%",
        f"Taxa de faltas: "
        f"{data.no_show_rate if data.no_show_rate is not None else '—'}%",
        f"Pacientes ativos: "
        f"{data.active_patients if data.active_patients is not None else 'oculto'}",
        "",
        "Recortes abaixo do limiar de anonimização foram suprimidos para impedir "
        "reidentificação. Este relatório não contém texto livre de pacientes.",
    ]
    return "\n".join(lines)


def _persist_report(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    kind: str,
    title: str,
    period_start: date,
    period_end: date,
    sources: list[str],
    formulas: list[str],
    limitations: str,
    content: str,
    request_id: UUID,
) -> Report:
    report = Report(
        clinic_id=clinic_id,
        kind=kind,
        title=title,
        period_start=period_start,
        period_end=period_end,
        sources=sources,
        formulas=formulas,
        limitations=limitations,
        generated_by_id=actor.pk,
        status=ReportStatus.READY,
        download_key=secrets.token_hex(16),
        expires_at=timezone.now() + timedelta(hours=REPORT_TTL_HOURS),
    )
    report.file.save("relatorio.txt", ContentFile(content.encode("utf-8")), save=False)
    report.save(force_insert=True)
    report_generated.send(
        sender=Report,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(report.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="export",
        resource_type="report",
        resource_id=str(report.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return report


@transaction.atomic
def generate_individual_report(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
    request_id: UUID,
) -> Report:
    """Generate the patient's own individual report (re-authorized on download)."""
    data = patient_dashboard_metrics(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    generated_at = timezone.now()
    content = _individual_report_text(
        data=data, clinic_name=_clinic_name(clinic_id, actor), generated_at=generated_at
    )
    return _persist_report(
        clinic_id=clinic_id,
        actor=actor,
        kind=ReportKind.INDIVIDUAL,
        title="Relatório individual",
        period_start=period_start,
        period_end=period_end,
        sources=["diário", "check-in", "metas", "exercícios", "agenda"],
        formulas=[
            "checkin_frequency",
            "mood_distribution",
            "active_goals",
            "completed_exercises",
            "upcoming_appointments",
        ],
        limitations=(
            "Autorrelato descritivo; não é diagnóstico, recomendação ou causalidade."
        ),
        content=content,
        request_id=request_id,
    )


@transaction.atomic
def generate_operational_report(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
    request_id: UUID,
) -> Report:
    """Generate an anonymized operational report for a clinic administrator."""
    data = clinic_operational_metrics(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    generated_at = timezone.now()
    content = _operational_report_text(
        data=data, clinic_name=_clinic_name(clinic_id, actor), generated_at=generated_at
    )
    return _persist_report(
        clinic_id=clinic_id,
        actor=actor,
        kind=ReportKind.OPERATIONAL,
        title="Relatório operacional",
        period_start=period_start,
        period_end=period_end,
        sources=["agenda"],
        formulas=[
            "schedule_occupancy",
            "no_show_rate",
            "cancellations",
            "active_patients",
        ],
        limitations=(
            "Agregado e anonimizado acima do limiar; sem texto livre de pacientes."
        ),
        content=content,
        request_id=request_id,
    )


@transaction.atomic
def authorize_report_download(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    report_id: UUID,
    download_key: str,
    request_id: UUID,
) -> Report:
    """Re-authorize and record one report download via its temporary key."""
    report = (
        Report.objects.for_clinic(clinic_id)
        .filter(pk=report_id, download_key=download_key)
        .first()
    )
    if report is None:
        raise PermissionDenied
    if report.expires_at is not None and report.expires_at < timezone.now():
        raise PermissionDenied("O link de download expirou.")
    today = timezone.localdate()
    if report.kind == ReportKind.INDIVIDUAL:
        if report.generated_by_id != actor.pk or not has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role="patient", on_date=today
        ):
            raise PermissionDenied
    else:
        if not has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=today
        ):
            raise PermissionDenied

    report.downloaded_at = timezone.now()
    report.downloaded_by_id = actor.pk
    report.save(update_fields=("downloaded_at", "downloaded_by", "updated_at"))
    report_downloaded.send(
        sender=Report,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(report.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="view",
        resource_type="report",
        resource_id=str(report.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return report
