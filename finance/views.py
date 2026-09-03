"""HTTP views for service prices and accounts receivable."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.services import current_correlation_id
from scheduling.selectors import active_services_for_clinic

from .forms import ChargeCancelForm, ServicePriceForm
from .selectors import charges_visible_to
from .services import (
    cancel_charge,
    generate_charge_for_appointment,
    set_service_price,
    settle_charge,
)

__all__ = [
    "charge_cancel",
    "charge_generate",
    "charge_list",
    "charge_settle",
    "service_price_create",
]


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


@login_required
@require_GET
def charge_list(request: HttpRequest) -> HttpResponse:
    """Render the accounts-receivable list for an authorized finance actor."""
    clinic_id, actor = _clinic_and_actor(request)
    status = request.GET.get("status", "")
    rows = charges_visible_to(clinic_id=clinic_id, actor=actor, status=status)
    return TemplateResponse(
        request,
        "finance/charge_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Contas a receber",
            "charges": rows,
            "selected_status": status,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def service_price_create(request: HttpRequest) -> HttpResponse:
    """Create one effective service price."""
    clinic_id, actor = _clinic_and_actor(request)
    service_choices = [
        (str(service.pk), service.name)
        for service in active_services_for_clinic(clinic_id=clinic_id)
    ]
    form = ServicePriceForm(request.POST or None, service_choices=service_choices)
    if request.method == "POST" and form.is_valid():
        try:
            set_service_price(
                clinic_id=clinic_id,
                actor=actor,
                service_id=UUID(form.cleaned_data["service"]),
                amount=Decimal(form.cleaned_data["amount"]),
                currency=form.cleaned_data["currency"],
                valid_from=form.cleaned_data["valid_from"],
                valid_until=form.cleaned_data.get("valid_until"),
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("charge_list"))
    return TemplateResponse(
        request,
        "finance/service_price_form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Cadastrar preço",
            "form": form,
            "submit_label": "Salvar preço",
        },
    )


@login_required
@require_POST
def charge_generate(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    """Generate one charge from a confirmed appointment."""
    clinic_id, actor = _clinic_and_actor(request)
    generate_charge_for_appointment(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("charge_list"))


@login_required
@require_POST
def charge_settle(request: HttpRequest, charge_id: UUID) -> HttpResponse:
    """Record a manual payment for one charge."""
    clinic_id, actor = _clinic_and_actor(request)
    settle_charge(
        clinic_id=clinic_id,
        actor=actor,
        charge_id=charge_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("charge_list"))


@login_required
@require_POST
def charge_cancel(request: HttpRequest, charge_id: UUID) -> HttpResponse:
    """Cancel one charge with a recorded reason."""
    clinic_id, actor = _clinic_and_actor(request)
    form = ChargeCancelForm(request.POST)
    reason = form["reason"].value() if "reason" in form.data else ""
    cancel_charge(
        clinic_id=clinic_id,
        actor=actor,
        charge_id=charge_id,
        reason=reason or "",
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("charge_list"))
