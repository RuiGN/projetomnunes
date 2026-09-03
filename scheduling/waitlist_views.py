"""HTTP views for the reception waitlist."""

from __future__ import annotations

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
from people.selectors import patient_profiles_for_clinic

from .forms import WaitlistEntryForm
from .models import Unit
from .selectors import active_services_for_clinic, waitlist_entries_visible_to
from .waitlist_services import (
    add_waitlist_entry,
    cancel_waitlist_entry,
    fill_waitlist_entry,
)

__all__ = [
    "waitlist_add",
    "waitlist_cancel",
    "waitlist_fill",
    "waitlist_list",
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
def waitlist_list(request: HttpRequest) -> HttpResponse:
    """Render the reception waitlist for an authorized actor."""
    clinic_id, actor = _clinic_and_actor(request)
    status = request.GET.get("status", "")
    entries = waitlist_entries_visible_to(
        clinic_id=clinic_id, actor=actor, status=status
    )
    return TemplateResponse(
        request,
        "scheduling/waitlist_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Lista de espera",
            "entries": entries,
            "selected_status": status,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def waitlist_add(request: HttpRequest) -> HttpResponse:
    """Add one waitlist entry with period and unit preference."""
    clinic_id, actor = _clinic_and_actor(request)
    patient_choices = [
        (str(profile.pk), profile.full_name)
        for profile in patient_profiles_for_clinic(clinic_id=clinic_id)
    ]
    unit_choices = [
        (str(unit.pk), unit.name)
        for unit in Unit.objects.for_clinic(clinic_id).filter(is_active=True)
    ]
    service_choices = [
        (str(service.pk), service.name)
        for service in active_services_for_clinic(clinic_id=clinic_id)
    ]
    form = WaitlistEntryForm(
        request.POST or None,
        patient_choices=patient_choices,
        unit_choices=unit_choices,
        service_choices=service_choices,
    )
    if request.method == "POST" and form.is_valid():
        try:
            add_waitlist_entry(
                clinic_id=clinic_id,
                actor=actor,
                patient_profile_id=UUID(form.cleaned_data["patient_profile"]),
                unit_id=UUID(form.cleaned_data["unit"]),
                service_id=UUID(form.cleaned_data["service"]),
                preferred_period=form.cleaned_data.get("preferred_period", ""),
                contact_note=form.cleaned_data.get("contact_note", ""),
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("waitlist_list"))
    return TemplateResponse(
        request,
        "scheduling/waitlist_form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Adicionar à lista de espera",
            "form": form,
            "submit_label": "Adicionar",
        },
    )


@login_required
@require_POST
def waitlist_cancel(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Cancel one waiting entry."""
    clinic_id, actor = _clinic_and_actor(request)
    cancel_waitlist_entry(
        clinic_id=clinic_id,
        actor=actor,
        entry_id=entry_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("waitlist_list"))


@login_required
@require_POST
def waitlist_fill(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Fill a canceled slot with one waiting entry after human confirmation."""
    clinic_id, actor = _clinic_and_actor(request)
    appointment_id = UUID(request.POST["appointment_id"])
    fill_waitlist_entry(
        clinic_id=clinic_id,
        actor=actor,
        entry_id=entry_id,
        appointment_id=appointment_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("waitlist_list"))
