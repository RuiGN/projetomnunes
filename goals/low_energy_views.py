"""HTTP views for the low-energy mode."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.services import current_correlation_id

from .low_energy_models import LowEnergyActionTemplate
from .low_energy_services import (
    activate_low_energy_mode,
    configure_low_energy_actions,
    deactivate_low_energy_mode,
    get_low_energy_state,
)


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError:
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
def low_energy_home(request: HttpRequest) -> HttpResponse:
    """Render the simplified low-energy screen (8.7.3.2)."""
    clinic_id, actor = _clinic_and_actor(request)
    session = get_low_energy_state(clinic_id=clinic_id, actor=actor)
    template = (
        LowEnergyActionTemplate.infrastructure_objects.filter(
            clinic_id=clinic_id,
            patient_profile__user_id=actor.pk,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )
    return TemplateResponse(
        request,
        "goals/low_energy.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Modo baixa energia",
            "session": session,
            "template": template,
        },
    )


@login_required
@require_POST
def low_energy_configure(request: HttpRequest) -> HttpResponse:
    """Save the versioned minimal-action set (8.7.3.1)."""
    clinic_id, actor = _clinic_and_actor(request)
    configure_low_energy_actions(
        clinic_id=clinic_id,
        actor=actor,
        action_1=request.POST.get("action_1", ""),
        action_2=request.POST.get("action_2", ""),
        action_3=request.POST.get("action_3", ""),
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("low_energy_home"))


@login_required
@require_POST
def low_energy_activate(request: HttpRequest) -> HttpResponse:
    """One-touch activation with non-alarmist confirmation (8.7.3.2)."""
    clinic_id, actor = _clinic_and_actor(request)
    duration_hours = request.POST.get("duration_hours", "8")
    if not duration_hours.isdigit():
        duration_hours = "8"
    activate_low_energy_mode(
        clinic_id=clinic_id,
        actor=actor,
        duration_hours=int(duration_hours),
        note=request.POST.get("note", ""),
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("low_energy_home"))


@login_required
@require_POST
def low_energy_deactivate(request: HttpRequest) -> HttpResponse:
    """Manual end of the low-energy period (8.7.3.4)."""
    clinic_id, actor = _clinic_and_actor(request)
    deactivate_low_energy_mode(
        clinic_id=clinic_id, actor=actor, request_id=_request_uuid()
    )
    return HttpResponseRedirect(reverse("low_energy_home"))
