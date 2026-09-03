"""Transactional services for therapeutic exercises, assignments, and executions."""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import patient_profile_for_user

from .exercise_models import (
    AssignmentStatus,
    ExerciseAssignment,
    ExerciseComment,
    ExerciseExecution,
    ExerciseStatus,
    ExerciseVisibility,
    ResponseFormat,
    TherapeuticExercise,
)

__all__ = [
    "Service",
    "assign_exercise",
    "comment_on_execution",
    "confirm_assignment",
    "create_exercise",
    "ensure_default_exercises_for_clinic",
    "save_execution_draft",
    "start_or_resume_execution",
    "submit_execution",
    "update_exercise",
]


def _check_therapist_or_admin(clinic_id: UUID, actor: AbstractBaseUser) -> None:
    on_date = timezone.localdate()
    is_therapist = has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=on_date
    )
    is_admin = has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=on_date
    )
    if not (is_therapist or is_admin):
        raise PermissionDenied(
            "Apenas profissionais ou administradores autorizados "
            "podem gerenciar exercícios."
        )


def _patient_profile_id_for(clinic_id: UUID, actor: AbstractBaseUser) -> UUID:
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


# --- Seed Default Exercises (8.7.4.4) ---


DEFAULT_EXERCISES_DATA = [
    {
        "title": "Respiração diafragmática (4-7-8)",
        "approach": "Mindfulness / Respiração",
        "instructions": (
            "Inspire lentamente pelo nariz contando até 4. "
            "Retenha o ar contando até 7. "
            "Expire suavemente pela boca contando até 8. Repita o ciclo por 4 vezes."
        ),
        "estimated_minutes": 5,
        "response_format": ResponseFormat.SCALE_1_5,
        "accessibility_notes": "Pode ser feito sentado ou deitado.",
    },
    {
        "title": "Pausa de autocompaixão",
        "approach": "Autocompaixão",
        "instructions": (
            "1. Reconheça: 'Este é um momento de dificuldade'.\n"
            "2. Lembre-se: 'A dificuldade faz parte da vida de todas as pessoas'.\n"
            "3. Seja gentil consigo: 'Que eu possa me "
            "oferecer a bondade de que preciso'."
        ),
        "estimated_minutes": 10,
        "response_format": ResponseFormat.TEXT,
        "accessibility_notes": "Áudio ou leitura simples.",
    },
    {
        "title": "Bússola de valores pessoais",
        "approach": "ACT (Aceitação e Compromisso)",
        "instructions": (
            "Reflita sobre o que é verdadeiramente importante para você nas áreas: "
            "Relacionamentos, Trabalho/Saúde e Cuidado pessoal. "
            "Escreva 1 pequena ação alinhada hoje."
        ),
        "estimated_minutes": 15,
        "response_format": ResponseFormat.TEXT,
        "accessibility_notes": "Orientação textual clara.",
    },
    {
        "title": "Resolução prática de problemas",
        "approach": "TCC (Terapia Cognitivo-Comportamental)",
        "instructions": (
            "1. Defina o problema claramente.\n"
            "2. Liste todas as soluções possíveis sem julgar.\n"
            "3. Avalie prós e contras das 2 melhores alternativas.\n"
            "4. Escolha uma ação simples para iniciar hoje."
        ),
        "estimated_minutes": 15,
        "response_format": ResponseFormat.TEXT,
        "accessibility_notes": "Dividido em etapas ordenadas.",
    },
]


@transaction.atomic
def ensure_default_exercises_for_clinic(
    *, clinic_id: UUID, author: AbstractBaseUser
) -> list[TherapeuticExercise]:
    """Provide seed exercises (8.7.4.4)."""
    _check_therapist_or_admin(clinic_id, author)
    existing_titles = set(
        TherapeuticExercise.objects.for_clinic(clinic_id).values_list(
            "title", flat=True
        )
    )
    created_list = []
    for data in DEFAULT_EXERCISES_DATA:
        if data["title"] in existing_titles:
            continue
        exercise = TherapeuticExercise(
            clinic_id=clinic_id,
            author_id=author.pk,
            title=str(data["title"]),
            instructions=str(data["instructions"]),
            approach=str(data["approach"]),
            estimated_minutes=cast(int, data["estimated_minutes"]),
            response_format=str(data["response_format"]),
            accessibility_notes=str(data["accessibility_notes"]),
            status=ExerciseStatus.PUBLISHED,
            version=1,
        )
        exercise.full_clean(validate_unique=False, validate_constraints=False)
        exercise.save(force_insert=True)
        created_list.append(exercise)
    return created_list


# --- Exercise CRUD (8.7.4.1 & 8.7.4.2) ---


@transaction.atomic
def create_exercise(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    title: str,
    instructions: str,
    approach: str = "Geral",
    estimated_minutes: int = 10,
    response_format: str = ResponseFormat.TEXT,
    accessibility_notes: str = "",
    status: str = ExerciseStatus.DRAFT,
    request_id: UUID,
) -> TherapeuticExercise:
    """Create a new exercise template (8.7.4.1)."""
    _check_therapist_or_admin(clinic_id, actor)
    if not title.strip():
        raise ValidationError("O título do exercício é obrigatório.")
    if not instructions.strip():
        raise ValidationError("As instruções do exercício são obrigatórias.")

    exercise = TherapeuticExercise(
        clinic_id=clinic_id,
        author_id=actor.pk,
        title=title.strip()[:255],
        instructions=instructions.strip(),
        approach=approach.strip()[:64] or "Geral",
        estimated_minutes=max(1, min(int(estimated_minutes), 120)),
        response_format=response_format,
        accessibility_notes=accessibility_notes.strip()[:255],
        status=status,
        version=1,
    )
    exercise.full_clean(validate_unique=False, validate_constraints=False)
    exercise.save(force_insert=True)
    return exercise


@transaction.atomic
def update_exercise(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    exercise_id: UUID,
    title: str,
    instructions: str,
    approach: str = "Geral",
    estimated_minutes: int = 10,
    response_format: str = ResponseFormat.TEXT,
    accessibility_notes: str = "",
    status: str = ExerciseStatus.PUBLISHED,
    request_id: UUID,
) -> TherapeuticExercise:
    """Update exercise. If published and assigned, creates a new version (8.7.4.2)."""
    _check_therapist_or_admin(clinic_id, actor)
    exercise = (
        TherapeuticExercise.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=exercise_id)
        .first()
    )
    if exercise is None:
        raise PermissionDenied("Exercício não encontrado.")

    is_assigned = ExerciseAssignment.infrastructure_objects.filter(
        clinic_id=clinic_id, exercise_id=exercise.pk
    ).exists()

    if is_assigned and exercise.status == ExerciseStatus.PUBLISHED:
        # Prevent retroactive modification of assigned versions: create new version
        new_version = TherapeuticExercise(
            clinic_id=clinic_id,
            author_id=actor.pk,
            title=title.strip()[:255],
            instructions=instructions.strip(),
            approach=approach.strip()[:64] or "Geral",
            estimated_minutes=max(1, min(int(estimated_minutes), 120)),
            response_format=response_format,
            accessibility_notes=accessibility_notes.strip()[:255],
            status=status,
            version=exercise.version + 1,
            parent_exercise=exercise,
        )
        new_version.full_clean(validate_unique=False, validate_constraints=False)
        new_version.save(force_insert=True)
        return new_version
    else:
        # Safe to update in place
        exercise.title = title.strip()[:255]
        exercise.instructions = instructions.strip()
        exercise.approach = approach.strip()[:64] or "Geral"
        exercise.estimated_minutes = max(1, min(int(estimated_minutes), 120))
        exercise.response_format = response_format
        exercise.accessibility_notes = accessibility_notes.strip()[:255]
        exercise.status = status
        exercise.full_clean(validate_unique=False, validate_constraints=False)
        exercise.save()
        return exercise


# --- Assignment (8.7.4.3) ---


@transaction.atomic
def assign_exercise(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    exercise_id: UUID,
    patient_profile_id: UUID,
    frequency: str = "Pontual",
    due_date: date | None = None,
    notes: str = "",
    request_id: UUID,
) -> ExerciseAssignment:
    """Assign a published exercise to a linked patient (8.7.4.3)."""
    _check_therapist_or_admin(clinic_id, actor)
    exercise = (
        TherapeuticExercise.objects.for_clinic(clinic_id)
        .filter(pk=exercise_id, status=ExerciseStatus.PUBLISHED)
        .first()
    )
    if exercise is None:
        raise ValidationError(
            "O exercício selecionado não está publicado ou não existe."
        )

    assignment = ExerciseAssignment(
        clinic_id=clinic_id,
        exercise=exercise,
        patient_profile_id=patient_profile_id,
        assigned_by_id=actor.pk,
        frequency=frequency.strip()[:64] or "Pontual",
        due_date=due_date,
        notes=notes.strip(),
        status=AssignmentStatus.ASSIGNED,
    )
    assignment.full_clean(validate_unique=False, validate_constraints=False)
    assignment.save(force_insert=True)
    return assignment


@transaction.atomic
def confirm_assignment(
    *, clinic_id: UUID, actor: AbstractBaseUser, assignment_id: UUID, request_id: UUID
) -> ExerciseAssignment:
    """Patient confirms an assignment (8.7.4.3)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    assignment = (
        ExerciseAssignment.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=assignment_id, patient_profile_id=profile_id)
        .first()
    )
    if assignment is None:
        raise PermissionDenied("Atribuição não encontrada.")

    assignment.confirmed_by_patient = True
    assignment.confirmed_at = timezone.now()
    assignment.save(
        update_fields=("confirmed_by_patient", "confirmed_at", "updated_at")
    )
    return assignment


# --- Execution (8.7.5.1 & 8.7.5.2) ---


@transaction.atomic
def start_or_resume_execution(
    *, clinic_id: UUID, actor: AbstractBaseUser, assignment_id: UUID, request_id: UUID
) -> ExerciseExecution:
    """Start or resume an exercise execution session (8.7.5.1)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    assignment = (
        ExerciseAssignment.objects.for_clinic(clinic_id)
        .filter(pk=assignment_id, patient_profile_id=profile_id)
        .first()
    )
    if assignment is None:
        raise PermissionDenied("Atribuição não encontrada.")

    existing_draft = (
        ExerciseExecution.objects.for_clinic(clinic_id)
        .filter(
            assignment_id=assignment.pk, patient_profile_id=profile_id, is_draft=True
        )
        .order_by("-started_at")
        .first()
    )
    if existing_draft is not None:
        return existing_draft

    execution = ExerciseExecution(
        clinic_id=clinic_id,
        assignment=assignment,
        patient_profile_id=profile_id,
        started_at=timezone.now(),
        is_draft=True,
        last_step_completed=0,
        response_data={},
        visibility=ExerciseVisibility.PRIVATE,
    )
    execution.full_clean(validate_unique=False, validate_constraints=False)
    execution.save(force_insert=True)
    return execution


@transaction.atomic
def save_execution_draft(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    execution_id: UUID,
    step_number: int,
    response_data: dict[str, object],
    request_id: UUID,
) -> ExerciseExecution:
    """Save execution draft step (8.7.5.1)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    execution = (
        ExerciseExecution.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=execution_id, patient_profile_id=profile_id, is_draft=True)
        .first()
    )
    if execution is None:
        raise PermissionDenied("Sessão de execução não encontrada.")

    execution.last_step_completed = max(0, step_number)
    execution.response_data = response_data
    execution.save(update_fields=("last_step_completed", "response_data", "updated_at"))
    return execution


@transaction.atomic
def submit_execution(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    execution_id: UUID,
    response_data: dict[str, object],
    visibility: str = ExerciseVisibility.PRIVATE,
    request_id: UUID,
) -> ExerciseExecution:
    """Submit finished exercise response (8.7.5.2)."""
    profile_id = _patient_profile_id_for(clinic_id, actor)
    execution = (
        ExerciseExecution.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=execution_id, patient_profile_id=profile_id)
        .first()
    )
    if execution is None:
        raise PermissionDenied("Sessão de execução não encontrada.")

    execution.response_data = response_data
    execution.visibility = visibility
    execution.is_draft = False
    execution.completed_at = timezone.now()
    execution.save()

    # Mark assignment completed
    assignment = execution.assignment
    assignment.status = AssignmentStatus.COMPLETED
    assignment.save(update_fields=("status", "updated_at"))

    return execution


# --- Comments (8.7.5.3) ---


@transaction.atomic
def comment_on_execution(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    execution_id: UUID,
    content: str,
    request_id: UUID,
) -> ExerciseComment:
    """Add therapist comment on authorized execution (8.7.5.3)."""
    _check_therapist_or_admin(clinic_id, actor)
    execution = (
        ExerciseExecution.objects.for_clinic(clinic_id)
        .select_for_update()
        .filter(pk=execution_id)
        .first()
    )
    if execution is None:
        raise PermissionDenied("Execução não encontrada.")

    # Apply semaphore rule: Vermelho (PRIVATE) blocks comments
    if execution.visibility == ExerciseVisibility.PRIVATE:
        raise PermissionDenied("Esta resposta foi marcada como privada pelo paciente.")

    if not content.strip():
        raise ValidationError("O comentário não pode ser vazio.")

    comment = ExerciseComment(
        clinic_id=clinic_id,
        execution=execution,
        author_id=actor.pk,
        content=content.strip(),
    )
    comment.full_clean(validate_unique=False, validate_constraints=False)
    comment.save(force_insert=True)
    return comment
