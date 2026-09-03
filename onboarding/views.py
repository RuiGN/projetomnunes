"""Onboarding views for clinic administrators and patients."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from consents.selectors import current_documents_for_actor
from core.services import current_correlation_id
from people.selectors import patient_profile_for_user

from .forms import PatientGoalsForm, PatientPreferencesForm
from .models import PatientOnboarding
from .selectors import clinic_onboarding_checklist
from .services import complete_patient_onboarding, record_patient_onboarding

_STEPS = ("goals", "preferences", "terms", "complete")
_NEXT_STEP = {"goals": "preferences", "preferences": "terms", "terms": "complete"}


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError:
        return uuid4()


def _clinic_id(request: HttpRequest) -> UUID:
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk)


@login_required
@require_GET
def clinic_onboarding(request: HttpRequest) -> HttpResponse:
    """Render the factual clinic onboarding checklist."""
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic_id = _clinic_id(request)
    items = clinic_onboarding_checklist(clinic_id=clinic_id, actor=actor)
    return TemplateResponse(
        request,
        "onboarding/clinic_checklist.html",
        {"layout_template": "layouts/vertical.html", "items": items},
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_onboarding(request: HttpRequest) -> HttpResponse:
    """Guide one patient through the stepped onboarding flow."""
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic_id = _clinic_id(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied
    onboarding = PatientOnboarding.infrastructure_objects.filter(
        clinic_id=clinic_id, patient_profile=profile
    ).first()

    if request.method == "POST":
        step = request.POST.get("step", "goals")
        if step == "goals":
            form = PatientGoalsForm(request.POST)
            if form.is_valid():
                record_patient_onboarding(
                    clinic_id=clinic_id,
                    actor=actor,
                    patient_profile_id=profile.pk,
                    goals=form.cleaned_data["goals"],
                    contact_preferences=(
                        onboarding.contact_preferences if onboarding else {}
                    ),
                    reminder_windows=(
                        onboarding.reminder_windows if onboarding else {}
                    ),
                    current_step=PatientOnboarding.Step.PREFERENCES,
                    request_id=_request_uuid(),
                )
                return HttpResponseRedirect(
                    f"{reverse('patient_onboarding')}?step=preferences"
                )
        elif step == "preferences":
            preferences_form = PatientPreferencesForm(request.POST)
            if preferences_form.is_valid():
                record_patient_onboarding(
                    clinic_id=clinic_id,
                    actor=actor,
                    patient_profile_id=profile.pk,
                    goals=onboarding.goals if onboarding else [],
                    contact_preferences=preferences_form.cleaned_data[
                        "contact_preferences"
                    ],
                    reminder_windows=preferences_form.cleaned_data["reminder_windows"],
                    current_step=PatientOnboarding.Step.TERMS,
                    request_id=_request_uuid(),
                )
                return HttpResponseRedirect(
                    f"{reverse('patient_onboarding')}?step=terms"
                )
        elif step == "terms":
            complete_patient_onboarding(
                clinic_id=clinic_id,
                actor=actor,
                patient_profile_id=profile.pk,
                request_id=_request_uuid(),
            )
            return HttpResponseRedirect(
                f"{reverse('patient_onboarding')}?step=complete"
            )

    current = onboarding.current_step if onboarding else PatientOnboarding.Step.GOALS
    requested = request.GET.get("step", "")
    step = requested if requested in _STEPS else current
    documents = current_documents_for_actor(clinic_id=clinic_id, actor=actor)
    context: dict[str, object] = {
        "layout_template": "layouts/vertical.html",
        "step": step,
        "steps": _STEPS,
        "onboarding": onboarding,
        "documents": documents,
    }
    if step == "goals":
        context["form"] = PatientGoalsForm(
            initial={"goals": "\n".join(onboarding.goals) if onboarding else ""}
        )
    elif step == "preferences":
        context["form"] = PatientPreferencesForm(
            initial={
                "contact_preferences": (
                    [c for c, on in onboarding.contact_preferences.items() if on]
                    if onboarding
                    else []
                ),
                "reminder_windows": (
                    [w for w, on in onboarding.reminder_windows.items() if on]
                    if onboarding
                    else []
                ),
            }
        )
    return TemplateResponse(request, "onboarding/patient_onboarding.html", context)
