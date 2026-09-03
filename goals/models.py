"""Therapeutic goals domain: versioned goals with tracked steps.

Model modules are re-exported here so Django and type checkers discover them.
"""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel

from .exercise_models import (  # noqa: F401
    AssignmentStatus,
    ExerciseAssignment,
    ExerciseComment,
    ExerciseExecution,
    ExerciseStatus,
    ExerciseVisibility,
    ResponseFormat,
    TherapeuticExercise,
)
from .low_energy_models import (  # noqa: F401
    LowEnergyActionTemplate,
    LowEnergyMode,
)


class GoalQuerySet(models.QuerySet["Goal"]):
    """Tenant-scoped goal queries."""

    def for_clinic(self, clinic_id: UUID) -> GoalQuerySet:
        return self.filter(clinic_id=clinic_id)


class GoalManager(models.Manager["Goal"]):
    """Refuse accidental global access to goals."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Goal queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> GoalQuerySet:
        return GoalQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureGoalManager(models.Manager["Goal"]):
    """Unrestricted goal access reserved for transactional services."""

    def get_queryset(self) -> GoalQuerySet:
        return GoalQuerySet(self.model, using=self._db)


class Goal(UUIDTimestampedModel):
    """One patient goal with tracked steps, priority, due date and visibility.

    Visibility follows the same traffic-light semantics as the journal:
    Verde (shareable), Amarelo (confirmation required), Vermelho (private).
    Sharing is NEVER inferred from co-authorship with a professional.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        PAUSED = "paused", "Pausada"
        COMPLETED = "completed", "Concluída"
        ARCHIVED = "archived", "Arquivada"

    class Priority(models.IntegerChoices):
        LOW = 1, "Baixa"
        MEDIUM = 2, "Média"
        HIGH = 3, "Alta"

    class Visibility(models.TextChoices):
        SHAREABLE = "shareable", "Verde"
        CONFIRMATION_REQUIRED = "confirmation_required", "Amarelo"
        PRIVATE = "private", "Vermelho"

    class Horizon(models.TextChoices):
        SHORT = "short", "Curto prazo"
        MEDIUM = "medium", "Médio prazo"
        LONG = "long", "Longo prazo"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="goals",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="goals",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="goals_created",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(max_length=4000, blank=True)
    horizon = models.CharField(
        max_length=16, choices=Horizon.choices, default=Horizon.SHORT
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices, default=Priority.MEDIUM
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    visibility = models.CharField(
        max_length=24,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
    )
    defining_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="goals_defined",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=255, blank=True)

    objects = GoalManager()
    infrastructure_objects = InfrastructureGoalManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "status"),
                name="goal_patient_status_idx",
            ),
            models.Index(
                fields=("clinic", "visibility"),
                name="goal_clinic_visibility_idx",
            ),
        ]


class GoalStepQuerySet(models.QuerySet["GoalStep"]):
    """Tenant-scoped goal step queries."""

    def for_clinic(self, clinic_id: UUID) -> GoalStepQuerySet:
        return self.filter(clinic_id=clinic_id)


class GoalStepManager(models.Manager["GoalStep"]):
    """Refuse global queries on goal steps."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("GoalStep queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> GoalStepQuerySet:
        return GoalStepQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureGoalStepManager(models.Manager["GoalStep"]):
    def get_queryset(self) -> GoalStepQuerySet:
        return GoalStepQuerySet(self.model, using=self._db)


class GoalStep(UUIDTimestampedModel):
    """One small tracked step belonging to a goal."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="goal_steps",
    )
    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    description = models.CharField(max_length=500)
    order = models.PositiveSmallIntegerField(default=1)
    is_done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by_id = models.UUIDField(null=True, blank=True)

    objects = GoalStepManager()
    infrastructure_objects = InfrastructureGoalStepManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("goal", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("goal", "order"),
                name="unique_step_order_per_goal",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "goal", "is_done"),
                name="goal_step_clinic_done_idx",
            ),
        ]


class GoalEventQuerySet(models.QuerySet["GoalEvent"]):
    """Append-only history of goal lifecycle events."""

    def for_clinic(self, clinic_id: UUID) -> GoalEventQuerySet:
        return self.filter(clinic_id=clinic_id)


class GoalEventManager(models.Manager["GoalEvent"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("GoalEvent queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> GoalEventQuerySet:
        return GoalEventQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureGoalEventManager(models.Manager["GoalEvent"]):
    def get_queryset(self) -> GoalEventQuerySet:
        return GoalEventQuerySet(self.model, using=self._db)


class GoalEvent(UUIDTimestampedModel):
    """Immutable lifecycle event: reopen, due-date change, completion, pause."""

    class Kind(models.TextChoices):
        CREATED = "created", "Criada"
        UPDATED = "updated", "Atualizada"
        DUE_DATE_CHANGED = "due_date_changed", "Prazo alterado"
        REOPENED = "reopened", "Reaberta"
        COMPLETED = "completed", "Concluída"
        PAUSED = "paused", "Pausada"
        RESUMED = "resumed", "Retomada"
        ARCHIVED = "archived", "Arquivada"
        STEP_DONE = "step_done", "Etapa concluída"
        STEP_UNDONE = "step_undone", "Etapa reaberta"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="goal_events",
    )
    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    actor_id = models.UUIDField()
    detail = models.JSONField(default=dict, blank=True)

    objects = GoalEventManager()
    infrastructure_objects = InfrastructureGoalEventManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "goal", "created_at"),
                name="goal_event_clinic_idx",
            ),
        ]
