"""Tenant-scoped professional directory views."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from clinics.services import (
    authorized_active_clinic,
    reactivate_professional_membership,
    suspend_professional_membership,
)
from core.services import current_correlation_id

from .events import patient_record_accessed
from .forms import PatientProfileForm
from .models import PatientProfile
from .selectors import (
    patient_profile_detail_for_actor,
    professional_directory_visible_to,
)
from .services import (
    invitation_expiration_after,
    issue_patient_invitation,
    register_patient_profile,
)


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError:
        return uuid4()


def _actor_and_clinic(
    request: HttpRequest, *, action: str = "professionals.manage"
) -> tuple[AbstractBaseUser, UUID]:
    actor = request.user
    clinic = getattr(request, "clinic", None)
    if not isinstance(actor, AbstractBaseUser) or clinic is None:
        raise PermissionDenied
    authorized_active_clinic(
        clinic_id=clinic.pk,
        actor=actor,
        action=action,
    )
    return actor, clinic.pk


@login_required
@require_GET
def professional_list(request: HttpRequest) -> HttpResponse:
    """Render the active clinic's authorized professional directory."""
    actor, clinic_id = _actor_and_clinic(request)
    rows = professional_directory_visible_to(
        clinic_id=clinic_id,
        actor=actor,
        status=request.GET.get("status", ""),
        role=request.GET.get("role", ""),
        specialty=request.GET.get("specialty", "").strip().lower(),
        on_date=date.today(),
    )
    return TemplateResponse(
        request,
        "people/professional_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "professionals": rows,
            "selected_status": request.GET.get("status", ""),
            "selected_role": request.GET.get("role", ""),
            "selected_specialty": request.GET.get("specialty", ""),
        },
    )


@login_required
@require_POST
def professional_suspend(request: HttpRequest, membership_id: UUID) -> HttpResponse:
    actor, clinic_id = _actor_and_clinic(request)
    suspend_professional_membership(
        clinic_id=clinic_id,
        actor=actor,
        membership_id=membership_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("professional_list"))


@login_required
@require_POST
def professional_reactivate(request: HttpRequest, membership_id: UUID) -> HttpResponse:
    actor, clinic_id = _actor_and_clinic(request)
    reactivate_professional_membership(
        clinic_id=clinic_id,
        actor=actor,
        membership_id=membership_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("professional_list"))


@login_required
@require_GET
def patient_list(request: HttpRequest) -> HttpResponse:
    """Render minimized profiles from the active authorized clinic only."""
    _actor, clinic_id = _actor_and_clinic(
        request,
        action="patient.demographics.read",
    )
    patients = PatientProfile.objects.for_clinic(clinic_id).order_by("full_name", "pk")
    return TemplateResponse(
        request,
        "people/patient_list.html",
        {"layout_template": "layouts/vertical.html", "patients": patients},
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_create(request: HttpRequest) -> HttpResponse:
    """Register a minimized manual patient record with server validation."""
    actor, clinic_id = _actor_and_clinic(request, action="patients.create")
    form = PatientProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            register_patient_profile(
                clinic_id=clinic_id,
                actor=actor,
                request_id=_request_uuid(),
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("patient_list"))
    return TemplateResponse(
        request,
        "people/patient_form.html",
        {"layout_template": "layouts/vertical.html", "form": form},
    )


@login_required
@require_POST
def patient_invite(request: HttpRequest, patient_profile_id: UUID) -> HttpResponse:
    """Issue one single-use invitation linked to an existing patient profile."""
    actor, clinic_id = _actor_and_clinic(request, action="invitation.issue")
    issue_patient_invitation(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=patient_profile_id,
        expires_at=invitation_expiration_after(days=7),
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("patient_list"))


@login_required
@require_GET
def patient_detail(request: HttpRequest, patient_profile_id: UUID) -> HttpResponse:
    """Render one authorized patient record and audit the access."""
    actor, clinic_id = _actor_and_clinic(request, action="patient.demographics.read")
    profile = patient_profile_detail_for_actor(
        clinic_id=clinic_id,
        actor=actor,
        patient_profile_id=patient_profile_id,
    )
    if profile is None:
        raise PermissionDenied
    patient_record_accessed.send(
        sender=PatientProfile,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(profile.pk),
        request_id=_request_uuid(),
    )
    return TemplateResponse(
        request,
        "people/patient_detail.html",
        {"layout_template": "layouts/vertical.html", "patient": profile},
    )
