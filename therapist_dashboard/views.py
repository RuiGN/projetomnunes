"""Therapist dashboard views."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.views.decorators.http import require_GET

from .selectors import therapist_dashboard_snapshot

_PAGE_SIZE = 10


def _clinic_id(request: HttpRequest) -> UUID:
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk)


@login_required
@require_GET
def therapist_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the factual therapist home with linked patients and metrics."""
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic_id = _clinic_id(request)
    snapshot = therapist_dashboard_snapshot(clinic_id=clinic_id, actor=actor)

    query = request.GET.get("q", "").strip().casefold()
    patients = snapshot.patients
    if query:
        patients = tuple(
            row
            for row in patients
            if query in row.full_name.casefold()
            or query in row.email.casefold()
            or query in (row.social_name or "").casefold()
        )
    incomplete_only = request.GET.get("status", "") == "incomplete"
    if incomplete_only:
        patients = tuple(row for row in patients if not row.phone)

    page = Paginator(patients, _PAGE_SIZE).get_page(request.GET.get("page", 1))

    return TemplateResponse(
        request,
        "therapist_dashboard/home.html",
        {
            "layout_template": "layouts/vertical.html",
            "snapshot": snapshot,
            "patients": page,
            "query": request.GET.get("q", ""),
            "incomplete_only": incomplete_only,
        },
    )
