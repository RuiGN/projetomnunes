"""Guarded authoring services for the PRD 8.12.2 learning curriculum."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update

from .models import (
    Cohort,
    CohortMember,
    Course,
    CourseModule,
    CoursePrerequisite,
    CourseStatus,
    Lesson,
    LessonMaterial,
    Quiz,
    QuizQuestion,
    QuizStatus,
)


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


@transaction.atomic
def create_course_module(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    title: str,
    position: int,
    request_id: UUID,
) -> CourseModule:
    """Insert one draft module at the requested stable position."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    course = (
        Course.infrastructure_objects.select_for_update()
        .filter(pk=course_id, clinic_id=clinic_id)
        .first()
    )
    if course is None:
        raise PermissionDenied
    if course.status != CourseStatus.DRAFT:
        raise ValidationError("Somente cursos em rascunho podem receber módulos.")
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("O título do módulo é obrigatório.")
    existing_count = CourseModule.infrastructure_objects.filter(
        clinic_id=clinic_id, course_id=course.pk
    ).count()
    if position < 1 or position > existing_count + 1:
        raise ValidationError(
            "A posição do módulo deve estar entre 1 e %(max)d.",
            params={"max": existing_count + 1},
        )
    siblings = list(
        CourseModule.infrastructure_objects.filter(
            clinic_id=clinic_id,
            course_id=course.pk,
            position__gte=position,
        ).order_by("-position")
    )
    for sibling in siblings:
        sibling.position += 1
        sibling.save(update_fields=("position", "updated_at"))
    module = CourseModule.infrastructure_objects.create(
        clinic_id=clinic_id,
        course=course,
        title=clean_title,
        position=position,
        status=CourseStatus.DRAFT,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="course_module",
        resource_id=str(module.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(CourseModule, module)


@transaction.atomic
def create_lesson(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    module_id: UUID,
    title: str,
    duration_minutes: int,
    request_id: UUID,
    position: int | None = None,
) -> Lesson:
    """Insert one draft lesson at the requested position inside a tenant module."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    module = (
        CourseModule.infrastructure_objects.select_for_update()
        .filter(pk=module_id, clinic_id=clinic_id)
        .select_related("course")
        .first()
    )
    if module is None:
        raise PermissionDenied
    if module.course.status != CourseStatus.DRAFT:
        raise ValidationError("Somente cursos em rascunho podem receber aulas.")
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("O título da aula é obrigatório.")
    if duration_minutes <= 0:
        raise ValidationError("A duração da aula deve ser maior que zero.")
    existing_count = Lesson.infrastructure_objects.filter(
        clinic_id=clinic_id, module_id=module.pk
    ).count()
    if position is None:
        position = existing_count + 1
    if position < 1 or position > existing_count + 1:
        raise ValidationError(
            "A posição da aula deve estar entre 1 e %(max)d.",
            params={"max": existing_count + 1},
        )
    for sibling in Lesson.infrastructure_objects.filter(
        clinic_id=clinic_id,
        module_id=module.pk,
        position__gte=position,
    ).order_by("-position"):
        sibling.position += 1
        sibling.save(update_fields=("position", "updated_at"))
    lesson = Lesson.infrastructure_objects.create(
        clinic_id=clinic_id,
        module=module,
        title=clean_title,
        duration_minutes=duration_minutes,
        position=position,
        status=CourseStatus.DRAFT,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="lesson",
        resource_id=str(lesson.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(Lesson, lesson)


@transaction.atomic
def create_lesson_material(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    lesson_id: UUID,
    title: str,
    url: str,
    position: int,
    request_id: UUID,
) -> LessonMaterial:
    """Insert one ordered lesson material with a validated URL."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    lesson = (
        Lesson.infrastructure_objects.select_for_update()
        .filter(pk=lesson_id, clinic_id=clinic_id)
        .select_related("module__course")
        .first()
    )
    if lesson is None:
        raise PermissionDenied
    if lesson.module.course.status != CourseStatus.DRAFT:
        raise ValidationError("Somente cursos em rascunho podem receber materiais.")
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("O título do material é obrigatório.")
    clean_url = (url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValidationError("Informe uma URL válida (http/https) para o material.")
    existing_count = LessonMaterial.infrastructure_objects.filter(
        clinic_id=clinic_id, lesson_id=lesson.pk
    ).count()
    if position < 1 or position > existing_count + 1:
        raise ValidationError(
            "A posição do material deve estar entre 1 e %(max)d.",
            params={"max": existing_count + 1},
        )
    for sibling in LessonMaterial.infrastructure_objects.filter(
        clinic_id=clinic_id,
        lesson_id=lesson.pk,
        position__gte=position,
    ).order_by("-position"):
        sibling.position += 1
        sibling.save(update_fields=("position", "updated_at"))
    material = LessonMaterial.infrastructure_objects.create(
        clinic_id=clinic_id,
        lesson=lesson,
        title=clean_title,
        url=clean_url,
        position=position,
        status=CourseStatus.DRAFT,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="lesson_material",
        resource_id=str(material.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(LessonMaterial, material)


def _prerequisite_would_cycle(course: Course, prerequisite: Course) -> bool:
    """Return whether adding prerequisite closes a cycle from course upwards."""
    frontier = [prerequisite.pk]
    seen: set[UUID] = set()
    while frontier:
        current = frontier.pop()
        if current == course.pk:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(
            CoursePrerequisite.infrastructure_objects.filter(
                course_id=current
            ).values_list("prerequisite_course_id", flat=True)
        )
    return False


@transaction.atomic
def add_course_prerequisite(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    prerequisite_course_id: UUID,
    request_id: UUID,
) -> CoursePrerequisite:
    """Add one tenant-local prerequisite edge with cycle protection."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    course = (
        Course.infrastructure_objects.select_for_update()
        .filter(pk=course_id, clinic_id=clinic_id)
        .first()
    )
    if course is None:
        raise PermissionDenied
    if course.status != CourseStatus.DRAFT:
        raise ValidationError(
            "Somente cursos em rascunho podem receber pré-requisitos."
        )
    prerequisite = Course.infrastructure_objects.filter(
        pk=prerequisite_course_id, clinic_id=clinic_id
    ).first()
    if prerequisite is None:
        raise PermissionDenied
    if prerequisite.pk == course.pk:
        raise ValidationError("Um curso não pode ser pré-requisito de si mesmo.")
    existing = CoursePrerequisite.infrastructure_objects.filter(
        course_id=course.pk, prerequisite_course_id=prerequisite.pk
    ).first()
    if existing is not None:
        return cast(CoursePrerequisite, existing)
    if _prerequisite_would_cycle(course, prerequisite):
        raise ValidationError("Este vínculo criaria um ciclo de pré-requisitos.")
    edge = CoursePrerequisite.infrastructure_objects.create(
        clinic_id=clinic_id,
        course=course,
        prerequisite_course=prerequisite,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="course_prerequisite",
        resource_id=str(edge.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(CoursePrerequisite, edge)


@transaction.atomic
def create_cohort(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    name: str,
    request_id: UUID,
) -> Cohort:
    """Create one tenant-unique cohort under clinic administration."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError("O nome da coorte é obrigatório.")
    if Cohort.infrastructure_objects.filter(
        clinic_id=clinic_id, name__iexact=clean_name
    ).exists():
        raise ValidationError("Já existe uma coorte com este nome.")
    cohort = Cohort.infrastructure_objects.create(clinic_id=clinic_id, name=clean_name)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="cohort",
        resource_id=str(cohort.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(Cohort, cohort)


@transaction.atomic
def add_cohort_member(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    cohort_id: UUID,
    user_id: UUID,
    request_id: UUID,
) -> CohortMember:
    """Add one user with an active membership in this clinic to a cohort."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    cohort = (
        Cohort.infrastructure_objects.select_for_update()
        .filter(pk=cohort_id, clinic_id=clinic_id)
        .first()
    )
    if cohort is None:
        raise PermissionDenied
    from clinics.services import ClinicMembership

    member = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user_id, is_active=True)
        .first()
    )
    if member is None:
        raise ValidationError("O usuário precisa ter vínculo ativo nesta clínica.")
    existing = CohortMember.infrastructure_objects.filter(
        cohort_id=cohort.pk, user_id=user_id
    ).first()
    if existing is not None:
        return cast(CohortMember, existing)
    cohort_member = CohortMember.infrastructure_objects.create(
        clinic_id=clinic_id, cohort=cohort, user_id=user_id
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="cohort_member",
        resource_id=str(cohort_member.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(CohortMember, cohort_member)


@transaction.atomic
def create_quiz(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    slug: str,
    title: str,
    minimum_grade: int,
    max_attempts: int,
    shuffle_questions: bool,
    request_id: UUID,
) -> Quiz:
    """Create one explicit draft educational quiz for a tenant course."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        raise PermissionDenied
    clean_title = title.strip()
    clean_slug = slug.strip()
    if not clean_title or not clean_slug:
        raise ValidationError("Título e slug do questionário são obrigatórios.")
    if not 0 <= minimum_grade <= 100:
        raise ValidationError("A nota mínima deve estar entre 0 e 100.")
    if max_attempts <= 0:
        raise ValidationError("O número de tentativas deve ser maior que zero.")
    if Quiz.infrastructure_objects.filter(
        clinic_id=clinic_id, slug=clean_slug
    ).exists():
        raise ValidationError("Já existe um questionário com este slug.")
    quiz = Quiz.infrastructure_objects.create(
        clinic_id=clinic_id,
        course=course,
        slug=clean_slug,
        title=clean_title,
        minimum_grade=minimum_grade,
        max_attempts=max_attempts,
        shuffle_questions=shuffle_questions,
        status=QuizStatus.DRAFT,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="quiz",
        resource_id=str(quiz.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(Quiz, quiz)


@transaction.atomic
def create_quiz_question(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    quiz_id: UUID,
    prompt: str,
    options: dict[str, str],
    correct_key: str,
    explanation: str,
    position: int,
    request_id: UUID,
) -> QuizQuestion:
    """Insert one ordered question with options containing the correct key."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    quiz = (
        Quiz.infrastructure_objects.select_for_update()
        .filter(pk=quiz_id, clinic_id=clinic_id)
        .first()
    )
    if quiz is None:
        raise PermissionDenied
    if quiz.status != QuizStatus.DRAFT:
        raise ValidationError(
            "Somente questionários em rascunho podem receber questões."
        )
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValidationError("O enunciado da questão é obrigatório.")
    clean_options = {
        str(key).strip(): str(value).strip()
        for key, value in (options or {}).items()
        if str(value).strip()
    }
    if len(clean_options) < 2:
        raise ValidationError("Informe ao menos duas opções não vazias.")
    if correct_key not in clean_options:
        raise ValidationError("A chave correta deve estar entre as opções.")
    existing_count = QuizQuestion.infrastructure_objects.filter(
        clinic_id=clinic_id, quiz_id=quiz.pk
    ).count()
    if position < 1 or position > existing_count + 1:
        raise ValidationError(
            "A posição da questão deve estar entre 1 e %(max)d.",
            params={"max": existing_count + 1},
        )
    for sibling in QuizQuestion.infrastructure_objects.filter(
        clinic_id=clinic_id,
        quiz_id=quiz.pk,
        position__gte=position,
    ).order_by("-position"):
        sibling.position += 1
        sibling.save(update_fields=("position", "updated_at"))
    question = QuizQuestion.infrastructure_objects.create(
        clinic_id=clinic_id,
        quiz=quiz,
        prompt=clean_prompt,
        options=clean_options,
        correct_key=correct_key,
        explanation=explanation.strip(),
        position=position,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="quiz_question",
        resource_id=str(question.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(QuizQuestion, question)


@transaction.atomic
def publish_quiz(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    quiz_id: UUID,
    request_id: UUID,
) -> Quiz:
    """Publish one educational quiz after validating question readiness."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    quiz = (
        Quiz.infrastructure_objects.select_for_update()
        .filter(pk=quiz_id, clinic_id=clinic_id)
        .first()
    )
    if quiz is None:
        raise PermissionDenied
    if quiz.status == QuizStatus.PUBLISHED:
        return cast(Quiz, quiz)
    if quiz.status != QuizStatus.DRAFT:
        raise ValidationError("Somente questionários em rascunho podem ser publicados.")
    questions = QuizQuestion.infrastructure_objects.filter(
        clinic_id=clinic_id, quiz_id=quiz.pk
    )
    if not questions.exists():
        raise ValidationError(
            "O questionário precisa de ao menos uma questão antes de publicar."
        )
    quiz.status = QuizStatus.PUBLISHED
    quiz.save(update_fields=("status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="quiz",
        resource_id=str(quiz.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return cast(Quiz, quiz)
