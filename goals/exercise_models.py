"""Therapeutic exercises catalog, assignments, executions, and comments."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel


class ExerciseStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PUBLISHED = "published", "Publicado"
    ARCHIVED = "archived", "Arquivado"


class ResponseFormat(models.TextChoices):
    TEXT = "text", "Texto livre"
    SCALE_1_5 = "scale_1_5", "Escala de 1 a 5"
    SINGLE_CHOICE = "single_choice", "Escolha única"
    MULTIPLE_CHOICE = "multiple_choice", "Múltipla escolha"


class AssignmentStatus(models.TextChoices):
    ASSIGNED = "assigned", "Atribuído"
    COMPLETED = "completed", "Concluído"
    CANCELLED = "cancelled", "Cancelado"


class ExerciseVisibility(models.TextChoices):
    SHAREABLE = "shareable", "Verde (compartilhado)"
    CONFIRMATION_REQUIRED = "confirmation_required", "Amarelo (perguntar antes)"
    PRIVATE = "private", "Vermelho (somente eu)"


# --- Exercise Model ---


class TherapeuticExerciseQuerySet(models.QuerySet["TherapeuticExercise"]):
    def for_clinic(self, clinic_id: UUID) -> TherapeuticExerciseQuerySet:
        return self.filter(clinic_id=clinic_id)


class TherapeuticExerciseManager(models.Manager["TherapeuticExercise"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "TherapeuticExercise queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> TherapeuticExerciseQuerySet:
        return TherapeuticExerciseQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureTherapeuticExerciseManager(models.Manager["TherapeuticExercise"]):
    def get_queryset(self) -> TherapeuticExerciseQuerySet:
        return TherapeuticExerciseQuerySet(self.model, using=self._db)


class TherapeuticExercise(UUIDTimestampedModel):
    """Versioned therapeutic exercise template owned by a clinic (8.7.4.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="therapeutic_exercises",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_exercises",
    )
    title = models.CharField(max_length=255)
    instructions = models.TextField()
    approach = models.CharField(max_length=64, default="Geral")
    estimated_minutes = models.PositiveSmallIntegerField(default=10)
    response_format = models.CharField(
        max_length=32, choices=ResponseFormat.choices, default=ResponseFormat.TEXT
    )
    accessibility_notes = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=32, choices=ExerciseStatus.choices, default=ExerciseStatus.DRAFT
    )
    version = models.PositiveSmallIntegerField(default=1)
    parent_exercise = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="versions",
    )

    objects = TherapeuticExerciseManager()
    infrastructure_objects = InfrastructureTherapeuticExerciseManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "status"), name="exercise_clinic_status_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} (v{self.version})"


# --- Assignment Model ---


class ExerciseAssignmentQuerySet(models.QuerySet["ExerciseAssignment"]):
    def for_clinic(self, clinic_id: UUID) -> ExerciseAssignmentQuerySet:
        return self.filter(clinic_id=clinic_id)


class ExerciseAssignmentManager(models.Manager["ExerciseAssignment"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ExerciseAssignment queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ExerciseAssignmentQuerySet:
        return ExerciseAssignmentQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureExerciseAssignmentManager(models.Manager["ExerciseAssignment"]):
    def get_queryset(self) -> ExerciseAssignmentQuerySet:
        return ExerciseAssignmentQuerySet(self.model, using=self._db)


class ExerciseAssignment(UUIDTimestampedModel):
    """Assignment of an exercise to a patient by a therapist (8.7.4.3)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="exercise_assignments",
    )
    exercise = models.ForeignKey(
        TherapeuticExercise,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="exercise_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_exercises",
    )
    frequency = models.CharField(max_length=64, default="Pontual")
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    confirmed_by_patient = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
    )

    objects = ExerciseAssignmentManager()
    infrastructure_objects = InfrastructureExerciseAssignmentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "status"),
                name="assignment_patient_status_idx",
            ),
        ]


# --- Execution Model ---


class ExerciseExecutionQuerySet(models.QuerySet["ExerciseExecution"]):
    def for_clinic(self, clinic_id: UUID) -> ExerciseExecutionQuerySet:
        return self.filter(clinic_id=clinic_id)


class ExerciseExecutionManager(models.Manager["ExerciseExecution"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ExerciseExecution queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ExerciseExecutionQuerySet:
        return ExerciseExecutionQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureExerciseExecutionManager(models.Manager["ExerciseExecution"]):
    def get_queryset(self) -> ExerciseExecutionQuerySet:
        return ExerciseExecutionQuerySet(self.model, using=self._db)


class ExerciseExecution(UUIDTimestampedModel):
    """Patient's execution session for an assigned exercise (8.7.5.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="exercise_executions",
    )
    assignment = models.ForeignKey(
        ExerciseAssignment,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="exercise_executions",
    )
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    is_draft = models.BooleanField(default=True)
    last_step_completed = models.PositiveSmallIntegerField(default=0)
    response_data = models.JSONField(default=dict, blank=True)
    visibility = models.CharField(
        max_length=32,
        choices=ExerciseVisibility.choices,
        default=ExerciseVisibility.PRIVATE,
    )

    objects = ExerciseExecutionManager()
    infrastructure_objects = InfrastructureExerciseExecutionManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "visibility"),
                name="execution_patient_vis_idx",
            ),
        ]


# --- Comment Model ---


class ExerciseCommentQuerySet(models.QuerySet["ExerciseComment"]):
    def for_clinic(self, clinic_id: UUID) -> ExerciseCommentQuerySet:
        return self.filter(clinic_id=clinic_id)


class ExerciseCommentManager(models.Manager["ExerciseComment"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ExerciseComment queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ExerciseCommentQuerySet:
        return ExerciseCommentQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureExerciseCommentManager(models.Manager["ExerciseComment"]):
    def get_queryset(self) -> ExerciseCommentQuerySet:
        return ExerciseCommentQuerySet(self.model, using=self._db)


class ExerciseComment(UUIDTimestampedModel):
    """Asynchronous therapist comment on an authorized execution response (8.7.5.3)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="exercise_comments",
    )
    execution = models.ForeignKey(
        ExerciseExecution,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exercise_comments",
    )
    content = models.TextField()

    objects = ExerciseCommentManager()
    infrastructure_objects = InfrastructureExerciseCommentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "execution"), name="comment_clinic_execution_idx"
            ),
        ]
