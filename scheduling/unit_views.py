"""HTTP views for unit and room administration."""

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

from .forms import RoomForm, UnitForm
from .models import Unit
from .unit_services import (
    create_room,
    create_unit,
    deactivate_room,
    deactivate_unit,
    update_unit,
)

__all__ = [
    "room_create",
    "room_deactivate",
    "unit_create",
    "unit_deactivate",
    "unit_list",
    "unit_update",
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
def unit_list(request: HttpRequest) -> HttpResponse:
    """Render the clinic's units and their rooms."""
    clinic_id, _actor = _clinic_and_actor(request)
    units = list(
        Unit.objects.for_clinic(clinic_id)
        .prefetch_related("rooms")
        .order_by("name", "pk")
    )
    return TemplateResponse(
        request,
        "scheduling/unit_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Unidades e salas",
            "units": units,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def unit_create(request: HttpRequest) -> HttpResponse:
    """Create one unit."""
    clinic_id, actor = _clinic_and_actor(request)
    form = UnitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_unit(
                clinic_id=clinic_id,
                actor=actor,
                name=form.cleaned_data["name"],
                address={},
                timezone_name=form.cleaned_data["timezone_name"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("unit_list"))
    return TemplateResponse(
        request,
        "scheduling/unit_form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Nova unidade",
            "form": form,
            "submit_label": "Salvar unidade",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def unit_update(request: HttpRequest, unit_id: UUID) -> HttpResponse:
    """Update one unit's operational identity."""
    clinic_id, actor = _clinic_and_actor(request)
    unit = Unit.objects.for_clinic(clinic_id).filter(pk=unit_id).first()
    if unit is None:
        raise PermissionDenied
    form = UnitForm(
        request.POST or None,
        initial={"name": unit.name, "timezone_name": unit.timezone_name},
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_unit(
                clinic_id=clinic_id,
                actor=actor,
                unit_id=unit_id,
                name=form.cleaned_data["name"],
                address=unit.address,
                timezone_name=form.cleaned_data["timezone_name"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("unit_list"))
    return TemplateResponse(
        request,
        "scheduling/unit_form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Editar unidade",
            "form": form,
            "submit_label": "Salvar unidade",
        },
    )


@login_required
@require_POST
def unit_deactivate(request: HttpRequest, unit_id: UUID) -> HttpResponse:
    """Deactivate one unit, blocking when future appointments exist."""
    clinic_id, actor = _clinic_and_actor(request)
    deactivate_unit(
        clinic_id=clinic_id, actor=actor, unit_id=unit_id, request_id=_request_uuid()
    )
    return HttpResponseRedirect(reverse("unit_list"))


@login_required
@require_http_methods(["GET", "POST"])
def room_create(request: HttpRequest) -> HttpResponse:
    """Create one room inside a unit."""
    clinic_id, actor = _clinic_and_actor(request)
    unit_choices = [
        (str(unit.pk), unit.name)
        for unit in Unit.objects.for_clinic(clinic_id).filter(is_active=True)
    ]
    form = RoomForm(request.POST or None, unit_choices=unit_choices)
    if request.method == "POST" and form.is_valid():
        try:
            create_room(
                clinic_id=clinic_id,
                actor=actor,
                unit_id=UUID(form.cleaned_data["unit"]),
                name=form.cleaned_data["name"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("unit_list"))
    return TemplateResponse(
        request,
        "scheduling/room_form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Nova sala",
            "form": form,
            "submit_label": "Salvar sala",
        },
    )


@login_required
@require_POST
def room_deactivate(request: HttpRequest, room_id: UUID) -> HttpResponse:
    """Deactivate one room."""
    clinic_id, actor = _clinic_and_actor(request)
    deactivate_room(
        clinic_id=clinic_id, actor=actor, room_id=room_id, request_id=_request_uuid()
    )
    return HttpResponseRedirect(reverse("unit_list"))
