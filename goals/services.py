"""Transactional services for the goals domain."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import (
    linked_patients_for_therapist,
    patient_profile_for_user,
)

from .events import (
    goal_completed,
    goal_created,
    goal_due_date_changed,
    goal_reopened,
    goal_step_done,
    goal_step_undone,
    goal_updated,
    goal_visibility_changed,
)
from .models import Goal, GoalEvent, GoalStep

__all__ = [
    "Service",
    "complete_step",
    "create_goal",
    "goal_progress",
    "set_goal_status",
    "set_goal_visibility",
    "therapist_visible_goals",
    "update_goal",
]


def _patient_profile_id_for(clinic_id: UUID, actor: AbstractBaseUser) -> UUID:
    """Authorize self-service access and return the actor's own profile id."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied
    return profile.pk


def _record_event(
    *,
    clinic_id: UUID,
    goal_id: UUID,
    kind: str,
    actor: AbstractBaseUser,
    detail: dict[str, object] | None = None,
) -> None:
    GoalEvent.infrastructure_objects.create(
        clinic_id=clinic_id,
        goal_id=goal_id,
        kind=kind,
        actor_id=actor.pk,
        detail=detail or {},
    )


@transaction.atomic
def create_goal(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    title: str,
    description: str = "",
    horizon: str = Goal.Horizon.SHORT,
    priority: int = Goal.Priority.MEDIUM,
    due_date: date | None = None,
    steps: list[str] | None = None,
    visibility: str = Goal.Visibility.PRIVATE,
    request_id: UUID,
) -> Goal:
    """Create one patient-owned goal with small tracked steps."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("Dê um título à sua meta.")
    if horizon not in Goal.Horizon.values:
        raise ValidationError("Selecione um horizonte de tempo válido.")
    if priority not in Goal.Priority.values:
        raise ValidationError("Selecione uma prioridade válida.")
    if visibility not in Goal.Visibility.values:
        raise ValidationError("Selecione uma visibilidade válida.")
    clean_steps = [s.strip() for s in (steps or []) if s and s.strip()]
    if len(clean_steps) > 50:
        raise ValidationError("Uma meta pode ter no máximo 50 etapas.")

    goal = Goal(
        clinic_id=clinic_id,
        patient_profile_id=profile_id,
        author_id=actor.pk,
        title=clean_title,
        description=description.strip(),
        horizon=horizon,
        priority=priority,
        due_date=due_date,
        status=Goal.Status.ACTIVE,
        visibility=visibility,
        defining_actor_id=actor.pk,
    )
    goal.full_clean(validate_unique=False, validate_constraints=False)
    goal.save(force_insert=True)

    for index, step_description in enumerate(clean_steps, start=1):
        GoalStep.infrastructure_objects.create(
            clinic_id=clinic_id,
            goal=goal,
            description=step_description[:500],
            order=index,
        )

    _record_event(
        clinic_id=clinic_id,
        goal_id=goal.pk,
        kind=GoalEvent.Kind.CREATED,
        actor=actor,
    )
    goal_created.send(
        sender=Goal,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(goal.pk),
        request_id=request_id,
    )
    return goal


@transaction.atomic
def update_goal(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    goal_id: UUID,
    title: str,
    description: str = "",
    priority: int,
    due_date: date | None,
    request_id: UUID,
) -> Goal:
    """Edit one owned goal; due-date change is recorded in history."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    goal = (
        Goal.infrastructure_objects.select_for_update()
        .filter(
            pk=goal_id,
            clinic_id=clinic_id,
            patient_profile__user_id=actor.pk,
            status__in=[Goal.Status.ACTIVE, Goal.Status.PAUSED],
        )
        .first()
    )
    if goal is None:
        raise PermissionDenied

    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("Dê um título à sua meta.")
    if priority not in Goal.Priority.values:
        raise ValidationError("Selecione uma prioridade válida.")

    due_date_changed = goal.due_date != due_date
    old_due = goal.due_date
    goal.title = clean_title
    goal.description = description.strip()
    goal.priority = priority
    goal.due_date = due_date
    goal.full_clean(validate_unique=False, validate_constraints=False)
    goal.save()

    _record_event(
        clinic_id=clinic_id, goal_id=goal.pk, kind=GoalEvent.Kind.UPDATED, actor=actor
    )
    if due_date_changed:
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.DUE_DATE_CHANGED,
            actor=actor,
            detail={
                "from": str(old_due) if old_due else None,
                "to": str(due_date) if due_date else None,
            },
        )
        goal_due_date_changed.send(
            sender=Goal,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(goal.pk),
            request_id=request_id,
        )
    goal_updated.send(
        sender=Goal,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(goal.pk),
        request_id=request_id,
    )
    return goal


def goal_progress(*, goal: Goal) -> tuple[int, int, int]:
    """Return (done, total, percent) from completed steps."""
    steps = list(GoalStep.infrastructure_objects.filter(goal=goal))
    total = len(steps)
    done = sum(1 for step in steps if step.is_done)
    return done, total, (int(done / total * 100) if total else 0)


@transaction.atomic
def complete_step(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    step_id: UUID,
    is_done: bool,
    request_id: UUID,
) -> GoalStep:
    """Mark or unmark one small step, keeping progress and history."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    step = (
        GoalStep.infrastructure_objects.select_for_update()
        .filter(
            pk=step_id,
            clinic_id=clinic_id,
            goal__patient_profile__user_id=actor.pk,
        )
        .first()
    )
    if step is None:
        raise PermissionDenied

    if step.is_done == is_done:
        return step

    step.is_done = is_done
    step.done_at = timezone.now() if is_done else None
    step.done_by_id = actor.pk if is_done else None
    step.save(update_fields=("is_done", "done_at", "done_by_id", "updated_at"))

    _record_event(
        clinic_id=clinic_id,
        goal_id=step.goal_id,
        kind=GoalEvent.Kind.STEP_DONE if is_done else GoalEvent.Kind.STEP_UNDONE,
        actor=actor,
        detail={"step_id": str(step.pk)},
    )
    if is_done:
        goal_step_done.send(
            sender=GoalStep,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(step.goal_id),
            request_id=request_id,
        )
    else:
        goal_step_undone.send(
            sender=GoalStep,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(step.goal_id),
            request_id=request_id,
        )
    return step


@transaction.atomic
def set_goal_status(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    goal_id: UUID,
    status: str,
    reason: str = "",
    request_id: UUID,
) -> Goal:
    """Transition one goal's lifecycle status with non-punitive semantics."""
    if status not in Goal.Status.values:
        raise ValidationError("Estado inválido para a meta.")
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    goal = (
        Goal.infrastructure_objects.select_for_update()
        .filter(
            pk=goal_id,
            clinic_id=clinic_id,
            patient_profile__user_id=actor.pk,
        )
        .first()
    )
    if goal is None:
        raise PermissionDenied

    if goal.status == status:
        return goal

    now = timezone.now()
    if status == Goal.Status.COMPLETED:
        goal.completed_at = now
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.COMPLETED,
            actor=actor,
        )
        goal_completed.send(
            sender=Goal,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(goal.pk),
            request_id=request_id,
        )
    elif goal.status == Goal.Status.COMPLETED and status in {
        Goal.Status.ACTIVE,
        Goal.Status.PAUSED,
    }:
        # Reopening preserves history and clears completion timestamp
        goal.completed_at = None
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.REOPENED,
            actor=actor,
        )
        goal_reopened.send(
            sender=Goal,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(goal.pk),
            request_id=request_id,
        )
    elif status == Goal.Status.PAUSED:
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.PAUSED,
            actor=actor,
        )
    elif status == Goal.Status.ACTIVE and goal.status == Goal.Status.PAUSED:
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.RESUMED,
            actor=actor,
        )
    elif status == Goal.Status.ARCHIVED:
        _record_event(
            clinic_id=clinic_id,
            goal_id=goal.pk,
            kind=GoalEvent.Kind.ARCHIVED,
            actor=actor,
        )

    goal.status = status
    goal.closed_reason = "" if status != Goal.Status.ARCHIVED else reason.strip()
    goal.save()
    return goal


@transaction.atomic
def set_goal_visibility(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    goal_id: UUID,
    visibility: str,
    request_id: UUID,
) -> Goal:
    """Change one owned goal's traffic-light visibility and audit the transition."""
    if visibility not in Goal.Visibility.values:
        raise ValidationError("Selecione uma visibilidade válida.")
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    goal = (
        Goal.infrastructure_objects.select_for_update()
        .filter(pk=goal_id, clinic_id=clinic_id, patient_profile__user_id=actor.pk)
        .first()
    )
    if goal is None:
        raise PermissionDenied

    goal.visibility = visibility
    goal.save(update_fields=("visibility", "updated_at"))
    goal_visibility_changed.send(
        sender=Goal,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(goal.pk),
        request_id=request_id,
    )
    return goal


def therapist_visible_goals(
    *, clinic_id: UUID, therapist_id: UUID, on_date: date | None = None
) -> list[Goal]:
    """Return only explicitly shareable goals for one therapist's patients.

    Private (Vermelho) goals are NEVER returned. Confirmation-required
    (Amarelo) goals require an explicit active grant outside this selector.
    Sharing is never inferred from the professional having defined the goal.
    """
    today = on_date or timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=therapist_id,
        role="therapist",
        on_date=today,
    ):
        raise PermissionDenied
    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=therapist_id, on_date=today
    )
    profile_ids = {row.patient_profile_id for row in linked}
    if not profile_ids:
        return []
    return list(
        Goal.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id__in=profile_ids,
            visibility=Goal.Visibility.SHAREABLE,
        )
        .order_by("priority", "due_date", "-created_at")
    )
