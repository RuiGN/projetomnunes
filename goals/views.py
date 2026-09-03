"""HTTP views for the patient goals panel."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.services import current_correlation_id

from .forms import GoalForm
from .models import Goal
from .selectors import goal_steps_for_patient, patient_goals
from .services import (
    complete_step,
    create_goal,
    goal_progress,
    set_goal_status,
    set_goal_visibility,
    update_goal,
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


def _owned_goal(clinic_id: UUID, actor: AbstractBaseUser, goal_id: UUID) -> Goal:
    """Return one owned goal or deny access."""
    goal = (
        Goal.objects.for_clinic(clinic_id)
        .filter(pk=goal_id, patient_profile__user_id=actor.pk)
        .first()
    )
    if goal is None:
        raise PermissionDenied
    return goal


@login_required
@require_GET
def goal_list(request: HttpRequest) -> HttpResponse:
    """Render the patient's goals panel with progress and empty state."""
    clinic_id, actor = _clinic_and_actor(request)
    profile_exists = getattr(request, "clinic", None) is not None
    del profile_exists

    status_filter = request.GET.get("status", "")
    if status_filter and status_filter not in Goal.Status.values:
        status_filter = ""

    goals = patient_goals(clinic_id=clinic_id, actor=actor, status=status_filter)
    rows = []
    for goal in goals:
        done, total, percent = goal_progress(goal=goal)
        rows.append({"goal": goal, "done": done, "total": total, "percent": percent})

    return TemplateResponse(
        request,
        "goals/list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Minhas Metas",
            "rows": rows,
            "selected_status": status_filter,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def goal_create(request: HttpRequest) -> HttpResponse:
    """Create one goal with small tracked steps."""
    clinic_id, actor = _clinic_and_actor(request)
    form = GoalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        create_goal(
            clinic_id=clinic_id,
            actor=actor,
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description", ""),
            horizon=form.cleaned_data["horizon"],
            priority=form.cleaned_data["priority"],
            due_date=form.cleaned_data.get("due_date") or None,
            steps=form.cleaned_data.get("steps_raw") or [],
            visibility=form.cleaned_data["visibility"],
            request_id=_request_uuid(),
        )
        return HttpResponseRedirect(reverse("goal_list"))
    return TemplateResponse(
        request,
        "goals/form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Nova Meta",
            "form": form,
            "form_id": "goal-form",
            "submit_label": "Criar meta",
        },
    )


@login_required
@require_GET
def goal_detail(request: HttpRequest, goal_id: UUID) -> HttpResponse:
    """Render one owned goal with its steps and progress."""
    clinic_id, actor = _clinic_and_actor(request)
    goal = _owned_goal(clinic_id, actor, goal_id)
    steps = goal_steps_for_patient(clinic_id=clinic_id, actor=actor, goal_id=goal.pk)
    done, total, percent = goal_progress(goal=goal)
    return TemplateResponse(
        request,
        "goals/detail.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Detalhe da Meta",
            "goal": goal,
            "steps": steps,
            "done_count": done,
            "total_steps": total,
            "percent": percent,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def goal_edit(request: HttpRequest, goal_id: UUID) -> HttpResponse:
    """Edit one owned goal's title, priority and due date."""
    clinic_id, actor = _clinic_and_actor(request)
    goal = _owned_goal(clinic_id, actor, goal_id)

    initial = {
        "title": goal.title,
        "description": goal.description,
        "priority": str(goal.priority),
        "due_date": goal.due_date,
    }
    form = GoalForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        update_goal(
            clinic_id=clinic_id,
            actor=actor,
            goal_id=goal.pk,
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description", ""),
            priority=form.cleaned_data["priority"],
            due_date=form.cleaned_data.get("due_date"),
            request_id=_request_uuid(),
        )
        return HttpResponseRedirect(reverse("goal_detail", args=[goal.pk]))
    return TemplateResponse(
        request,
        "goals/form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Editar Meta",
            "form": form,
            "form_id": "goal-edit-form",
            "submit_label": "Salvar alterações",
        },
    )


@login_required
@require_POST
def goal_step_toggle(request: HttpRequest, step_id: UUID) -> HttpResponse:
    """Mark or unmark one small step."""
    clinic_id, actor = _clinic_and_actor(request)
    is_done = request.POST.get("is_done") == "true"
    complete_step(
        clinic_id=clinic_id,
        actor=actor,
        step_id=step_id,
        is_done=is_done,
        request_id=_request_uuid(),
    )
    next_url = request.POST.get("next") or reverse("goal_list")
    return HttpResponseRedirect(next_url)


@login_required
@require_POST
def goal_status_change(request: HttpRequest, goal_id: UUID) -> HttpResponse:
    """Transition one goal's lifecycle status."""
    clinic_id, actor = _clinic_and_actor(request)
    status = request.POST.get("status", "")
    set_goal_status(
        clinic_id=clinic_id,
        actor=actor,
        goal_id=goal_id,
        status=status,
        reason=request.POST.get("reason", ""),
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("goal_detail", args=[goal_id]))


@login_required
@require_POST
def goal_visibility_change(request: HttpRequest, goal_id: UUID) -> HttpResponse:
    """Change one goal's traffic-light visibility."""
    clinic_id, actor = _clinic_and_actor(request)
    set_goal_visibility(
        clinic_id=clinic_id,
        actor=actor,
        goal_id=goal_id,
        visibility=request.POST.get("visibility", ""),
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("goal_detail", args=[goal_id]))
