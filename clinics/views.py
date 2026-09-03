"""Tenant-scoped clinic setup views."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import Form
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.services import current_correlation_id

from .forms import (
    WEEKDAYS,
    ClinicBrandingForm,
    ClinicIdentityForm,
    ClinicModulesForm,
    ClinicOperationsForm,
)
from .models import ClinicConfiguration, CustomDomain
from .services import (
    authorized_active_clinic,
    update_clinic_branding,
    update_clinic_identity,
    update_clinic_modules,
    update_clinic_operations,
)
from .typing import ClinicRequest

SETUP_STAGES = (
    ("identity", "Dados institucionais"),
    ("operations", "Atendimento e horários"),
    ("branding", "Identidade visual"),
    ("modules", "Módulos"),
    ("review", "Revisão"),
)


def _first_incomplete_stage(configuration: ClinicConfiguration | None) -> str:
    """Derive ordered setup progress from persisted server-owned evidence."""
    if configuration is None:
        return "identity"
    expected_days = {day for day, _label in WEEKDAYS}
    if (
        not configuration.service_channels
        or set(configuration.weekly_hours) != expected_days
    ):
        return "operations"
    if not configuration.logo:
        return "branding"
    if configuration.modules_updated_at is None:
        return "modules"
    return "review"


def _request_uuid() -> UUID:
    """Return the correlation ID as UUID, with a safe fallback outside middleware."""
    try:
        return UUID(current_correlation_id())
    except ValueError:
        return uuid4()


@login_required
@require_http_methods(["GET", "POST"])
def clinic_setup(request: HttpRequest) -> HttpResponse:
    """Render and process the active tenant's ordered setup flow."""
    clinic_request = cast(ClinicRequest, request)
    actor = request.user
    clinic = clinic_request.clinic
    if not isinstance(actor, AbstractBaseUser) or clinic is None:
        raise PermissionDenied
    authorized_active_clinic(
        clinic_id=clinic.pk,
        actor=actor,
        action="clinic.manage",
    )
    requested_stage = (
        request.POST.get("stage", "identity")
        if request.method == "POST"
        else request.GET.get("stage", "identity")
    )
    stage_keys = {key for key, _label in SETUP_STAGES}
    current_stage = requested_stage if requested_stage in stage_keys else "identity"
    configuration = (
        ClinicConfiguration.objects.for_clinic(clinic.pk)
        .select_related("modules_updated_by")
        .first()
    )
    first_incomplete_stage = _first_incomplete_stage(configuration)
    stage_order = [key for key, _label in SETUP_STAGES]
    if stage_order.index(current_stage) > stage_order.index(first_incomplete_stage):
        return HttpResponseRedirect(
            f"{reverse('clinic_setup')}?stage={first_incomplete_stage}"
        )
    identity_initial = (
        {
            field: getattr(configuration, field)
            for field in ClinicIdentityForm.base_fields
        }
        if configuration is not None
        else None
    )
    form: Form
    if current_stage == "operations":
        operations_initial: dict[str, object] = {}
        if configuration is not None:
            operations_initial = {
                "timezone_name": configuration.timezone_name,
                "language_code": configuration.language_code,
                "service_channels": configuration.service_channels,
                "out_of_hours_instructions": configuration.out_of_hours_instructions,
            }
            for day, _label in WEEKDAYS:
                intervals = configuration.weekly_hours.get(day, [])
                operations_initial[f"{day}_start"] = (
                    intervals[0]["start"] if intervals else ""
                )
                operations_initial[f"{day}_end"] = (
                    intervals[0]["end"] if intervals else ""
                )
        form = ClinicOperationsForm(
            request.POST if request.method == "POST" else None,
            initial=operations_initial,
        )
    elif current_stage == "branding":
        form = ClinicBrandingForm(
            request.POST if request.method == "POST" else None,
            request.FILES if request.method == "POST" else None,
            initial=(
                {
                    "primary_color": configuration.primary_color,
                    "secondary_color": configuration.secondary_color,
                }
                if configuration is not None
                else None
            ),
        )
    elif current_stage == "modules":
        form = ClinicModulesForm(
            request.POST if request.method == "POST" else None,
            initial={
                "enabled_modules": (
                    configuration.enabled_modules
                    if configuration is not None and configuration.enabled_modules
                    else ["patient_management"]
                )
            },
        )
    else:
        form = ClinicIdentityForm(
            request.POST if request.method == "POST" else None,
            initial=identity_initial,
        )
    if request.method == "POST" and current_stage == "identity" and form.is_valid():
        try:
            update_clinic_identity(
                clinic_id=clinic.pk,
                actor=actor,
                request_id=_request_uuid(),
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(f"{reverse('clinic_setup')}?stage=operations")
    if request.method == "POST" and current_stage == "operations" and form.is_valid():
        operation_values = dict(form.cleaned_data)
        for day, _label in WEEKDAYS:
            operation_values.pop(f"{day}_start", None)
            operation_values.pop(f"{day}_end", None)
        try:
            update_clinic_operations(
                clinic_id=clinic.pk,
                actor=actor,
                request_id=_request_uuid(),
                **operation_values,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(f"{reverse('clinic_setup')}?stage=branding")
    if request.method == "POST" and current_stage == "branding" and form.is_valid():
        try:
            update_clinic_branding(
                clinic_id=clinic.pk,
                actor=actor,
                request_id=_request_uuid(),
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(f"{reverse('clinic_setup')}?stage=modules")
    if request.method == "POST" and current_stage == "modules" and form.is_valid():
        try:
            update_clinic_modules(
                clinic_id=clinic.pk,
                actor=actor,
                request_id=_request_uuid(),
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(f"{reverse('clinic_setup')}?stage=review")
    return TemplateResponse(
        request,
        "clinics/setup.html",
        {
            "layout_template": "layouts/vertical.html",
            "clinic_configuration": configuration,
            "setup_stages": SETUP_STAGES,
            "current_stage": current_stage,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET"])
def whitelabel_domains(request: HttpRequest) -> HttpResponse:
    """Render the active tenant's custom domains for clinic administrators."""
    clinic_request = cast(ClinicRequest, request)
    actor = request.user
    clinic = clinic_request.clinic
    if not isinstance(actor, AbstractBaseUser) or clinic is None:
        raise PermissionDenied
    authorized_active_clinic(
        clinic_id=clinic.pk,
        actor=actor,
        action="clinic.manage",
    )
    domains = list(
        CustomDomain.infrastructure_objects.filter(clinic_id=clinic.pk).order_by(
            "domain"
        )
    )
    return TemplateResponse(
        request,
        "clinics/whitelabel_domains.html",
        {
            "layout_template": "layouts/vertical.html",
            "domains": domains,
        },
    )
