"""HTTP views for dashboards and MVP reports."""

from __future__ import annotations

from datetime import date, timedelta
from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from clinics.policies import has_active_clinic_role
from core.services import current_correlation_id

from .forms import ReportPeriodForm
from .selectors import reports_visible_to
from .services import (
    authorize_report_download,
    clinic_operational_metrics,
    generate_individual_report,
    generate_operational_report,
    patient_dashboard_metrics,
    therapist_dashboard_metrics,
)

NON_DIAGNOSTIC_NOTICE = (
    "Estes indicadores descrevem autorrelatos e fatos registrados. Eles não "
    "constituem diagnóstico, recomendação clínica ou relação de causalidade."
)


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError, TypeError:
        return uuid4()


def _clinic_and_actor(request: HttpRequest) -> tuple[UUID, AbstractBaseUser]:
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk), actor


def _period(request: HttpRequest) -> tuple[date, date]:
    today = timezone.localdate()
    raw_start = request.GET.get("start", "")
    raw_end = request.GET.get("end", "")
    try:
        period_end = date.fromisoformat(raw_end) if raw_end else today
    except ValueError:
        period_end = today
    try:
        period_start = (
            date.fromisoformat(raw_start)
            if raw_start
            else period_end - timedelta(days=30)
        )
    except ValueError:
        period_start = period_end - timedelta(days=30)
    if period_end < period_start:
        period_start = period_end - timedelta(days=30)
    return period_start, period_end


@login_required
@require_GET
def patient_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the patient's own evolution dashboard (8.9.2)."""
    clinic_id, actor = _clinic_and_actor(request)
    period_start, period_end = _period(request)
    data = patient_dashboard_metrics(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    return TemplateResponse(
        request,
        "analytics/patient_dashboard.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Minha evolução",
            "data": data,
            "mood_labels": ("Muito mal", "Mal", "Neutro", "Bem", "Muito bem"),
            "non_diagnostic_notice": NON_DIAGNOSTIC_NOTICE,
        },
    )


@login_required
@require_GET
def therapist_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the therapist's authorized dashboard (8.9.3)."""
    clinic_id, actor = _clinic_and_actor(request)
    period_start, period_end = _period(request)
    data = therapist_dashboard_metrics(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    return TemplateResponse(
        request,
        "analytics/therapist_dashboard.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Painel profissional",
            "data": data,
            "non_diagnostic_notice": NON_DIAGNOSTIC_NOTICE,
        },
    )


@login_required
@require_GET
def clinic_panel(request: HttpRequest) -> HttpResponse:
    """Render the anonymized operational panel (8.9.4)."""
    clinic_id, actor = _clinic_and_actor(request)
    period_start, period_end = _period(request)
    data = clinic_operational_metrics(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    return TemplateResponse(
        request,
        "analytics/clinic_panel.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Painel operacional",
            "data": data,
            "non_diagnostic_notice": NON_DIAGNOSTIC_NOTICE,
        },
    )


@login_required
@require_GET
def report_list(request: HttpRequest) -> HttpResponse:
    """List reports the actor may see, with their temporary download links."""
    clinic_id, actor = _clinic_and_actor(request)
    reports = reports_visible_to(clinic_id=clinic_id, actor=actor)
    is_admin = has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    )
    is_patient = has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    )
    return TemplateResponse(
        request,
        "analytics/report_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Relatórios",
            "reports": reports,
            "form": ReportPeriodForm(),
            "can_generate": is_admin or is_patient,
        },
    )


@login_required
@require_POST
def report_generate(request: HttpRequest) -> HttpResponse:
    """Generate an individual or operational report from the actor's role."""
    clinic_id, actor = _clinic_and_actor(request)
    form = ReportPeriodForm(request.POST)
    if not form.is_valid():
        return HttpResponseRedirect(reverse("report_list"))
    period_start = form.cleaned_data["period_start"]
    period_end = form.cleaned_data["period_end"]
    today = timezone.localdate()
    if has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="patient", on_date=today
    ):
        generate_individual_report(
            clinic_id=clinic_id,
            actor=actor,
            period_start=period_start,
            period_end=period_end,
            request_id=_request_uuid(),
        )
    elif has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=today
    ):
        generate_operational_report(
            clinic_id=clinic_id,
            actor=actor,
            period_start=period_start,
            period_end=period_end,
            request_id=_request_uuid(),
        )
    else:
        raise PermissionDenied
    return HttpResponseRedirect(reverse("report_list"))


@login_required
@require_GET
def report_download(request: HttpRequest, report_id: UUID) -> FileResponse:
    """Serve one authorized, non-expired report by its temporary key."""
    clinic_id, actor = _clinic_and_actor(request)
    download_key = request.GET.get("key", "")
    report = authorize_report_download(
        clinic_id=clinic_id,
        actor=actor,
        report_id=report_id,
        download_key=download_key,
        request_id=_request_uuid(),
    )
    response = FileResponse(
        report.file.open("rb"),
        as_attachment=True,
        filename="relatorio.txt",
    )
    response["Cache-Control"] = "private, no-store"
    return response
