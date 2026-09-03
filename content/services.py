"""Transactional services for the editorial workflow and content indexing."""

from __future__ import annotations

import hashlib
import html
import html.parser
import json
import random
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import (
    PrivateDownloadGrant,
    PrivateUploadMetadata,
    PrivateUploadPolicy,
    require_clean_malware_scan,
)
from core.services import (
    Service as Service,
)

from .events import content_archived, content_published
from .models import (
    Certificate,
    Cohort,
    CohortMember,
    Content,
    ContentCategory,
    ContentKind,
    ContentMedia,
    ContentNotification,
    ContentRecommendation,
    ContentReport,
    ContentStatus,
    ContentTag,
    ContentVersion,
    ContentVersionComment,
    Course,
    CourseModule,
    CoursePrerequisite,
    CourseStatus,
    Enrollment,
    EnrollmentSource,
    LearningEvent,
    LearningPath,
    LearningPathCourse,
    Lesson,
    LessonCompletion,
    LessonFavorite,
    LessonMaterial,
    LessonProgress,
    PrivateNote,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    QuizStatus,
)

__all__ = [
    "Service",
    "complete_lesson",
    "recommend_content",
    "recommendations_for_patient",
    "retire_recommendation",
    "create_learning_path",
    "approve_content_version",
    "archive_content",
    "attach_media",
    "create_course",
    "create_content_version",
    "append_editorial_comment",
    "update_content_metadata",
    "publish_content_version",
    "publish_course",
    "rollback_content",
    "sanitize_body",
    "search_published_content",
    "start_content",
    "submit_for_review",
    "enroll_cohort",
    "enroll_individual",
    "issue_certificate",
    "quiz_attempt_feedback",
    "quiz_questions_for_participant",
    "revoke_certificate",
    "submit_quiz_attempt",
    "verify_certificate",
]

# ---------------------------------------------------------------------------
# 8.12.2 — learning products: paths, enrollment, quizzes and certificates
# ---------------------------------------------------------------------------


@transaction.atomic
def create_learning_path(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    slug: str,
    title: str,
    courses: list[dict[str, object]],
    request_id: UUID,
) -> LearningPath:
    """Create an ordered tenant learning path with tenant-local prerequisites."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized_slug = slug.strip().lower()
    if not normalized_slug or not title.strip():
        raise ValidationError("Informe slug e título da trilha.")
    if LearningPath.infrastructure_objects.filter(
        clinic_id=clinic_id, slug=normalized_slug
    ).exists():
        raise ValidationError("Já existe trilha com este slug.")
    path = LearningPath.infrastructure_objects.create(
        clinic_id=clinic_id, slug=normalized_slug, title=title.strip()
    )
    for position, entry in enumerate(courses, start=1):
        course = Course.infrastructure_objects.filter(
            pk=UUID(str(entry["course_id"])), clinic_id=clinic_id
        ).first()
        if course is None:
            raise PermissionDenied
        prerequisite_id = entry.get("prerequisite_course_id")
        if prerequisite_id is not None:
            prerequisite = Course.infrastructure_objects.filter(
                pk=UUID(str(prerequisite_id)), clinic_id=clinic_id
            ).first()
            if prerequisite is None:
                raise PermissionDenied
            if prerequisite.pk == course.pk:
                raise ValidationError(
                    "Um curso não pode ser pré-requisito de si mesmo."
                )
            CoursePrerequisite.infrastructure_objects.get_or_create(
                clinic_id=clinic_id,
                course_id=course.pk,
                prerequisite_course_id=prerequisite.pk,
            )
        LearningPathCourse.infrastructure_objects.create(
            clinic_id=clinic_id,
            path=path,
            course_id=course.pk,
            position=position,
        )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="learning_path",
        resource_id=str(path.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return path  # type: ignore[no-any-return]


def _require_course_access(*, clinic_id: UUID, course: Course, now: datetime) -> None:
    if course.status != CourseStatus.PUBLISHED:
        raise ValidationError("Este curso não está disponível.")
    if course.available_from is not None and course.available_from > now:
        raise ValidationError("Este curso ainda não está aberto para matrícula.")
    if course.available_until is not None and course.available_until < now:
        raise ValidationError("O período de matrícula deste curso já encerrou.")
    active = Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id, course=course, ended_at__isnull=True
    ).count()
    if course.capacity is not None and active >= course.capacity:
        raise ValidationError("Todas as vagas deste curso já foram preenchidas.")


def _prerequisite_is_completed(
    *, clinic_id: UUID, prerequisite_course_id: UUID, user_id: UUID
) -> bool:
    total = Lesson.infrastructure_objects.filter(
        clinic_id=clinic_id, module__course_id=prerequisite_course_id
    ).count()
    completed = LessonCompletion.infrastructure_objects.filter(
        clinic_id=clinic_id,
        lesson__module__course_id=prerequisite_course_id,
        user_id=user_id,
    ).count()
    return total > 0 and total == completed


def _require_completed_prerequisites(
    *, clinic_id: UUID, course: Course, user_id: UUID
) -> None:
    """Reject enrollment while any tenant course prerequisite is incomplete."""
    prerequisite_ids = CoursePrerequisite.infrastructure_objects.filter(
        clinic_id=clinic_id, course=course
    ).values_list("prerequisite_course_id", flat=True)
    for prerequisite_course_id in prerequisite_ids:
        if not _prerequisite_is_completed(
            clinic_id=clinic_id,
            prerequisite_course_id=prerequisite_course_id,
            user_id=user_id,
        ):
            raise ValidationError(
                "Conclua os pré-requisitos do curso antes de se matricular."
            )


@transaction.atomic
def enroll_individual(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    course_id: UUID,
    plan_codes: set[str],
    invitation_id: UUID | None,
    idempotency_key: UUID,
) -> Enrollment:
    """Enroll one authorized learner under the course access rules."""
    from clinics.services import ClinicMembership

    lock_clinic_for_update(clinic_id=clinic_id)
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        raise PermissionDenied
    replayed = Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user.pk,
        idempotency_key=idempotency_key,
    ).first()
    if replayed is not None:
        return replayed  # type: ignore[no-any-return]
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if course.required_plan_code and course.required_plan_code not in plan_codes:
        raise PermissionDenied
    if course.invitation_required:
        if invitation_id is None:
            raise PermissionDenied
        from accounts.services import ClinicInvitation

        invitation = ClinicInvitation.infrastructure_objects.filter(
            pk=invitation_id, clinic_id=clinic_id
        ).first()
        if (
            invitation is None
            or invitation.revoked_at is not None
            or invitation.used_at is not None
            or invitation.expires_at <= timezone.now()
            or invitation.recipient_email != _actor_email(user)
        ):
            raise PermissionDenied
    _require_course_access(clinic_id=clinic_id, course=course, now=timezone.now())
    _require_completed_prerequisites(
        clinic_id=clinic_id, course=course, user_id=user.pk
    )
    if Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user.pk,
        ended_at__isnull=True,
    ).exists():
        raise ValidationError("Este participante já possui matrícula neste curso.")
    enrollment = Enrollment.infrastructure_objects.create(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user.pk,
        source=EnrollmentSource.INDIVIDUAL,
        idempotency_key=idempotency_key,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create",
        resource_type="enrollment",
        resource_id=str(enrollment.pk),
        outcome="success",
        request_id=idempotency_key,
        network_origin=None,
    )
    return enrollment  # type: ignore[no-any-return]


@transaction.atomic
def enroll_cohort(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    cohort_id: UUID,
    idempotency_key: UUID,
) -> list[Enrollment]:
    """Enroll every active cohort member once, idempotently.

    Admin-vouching semantics (accepted in review round 2): the clinic admin
    enrolling a cohort vouches for the course access rules, including plan
    gates and prerequisites, that individual enrollment would enforce.
    """
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    cohort = Cohort.infrastructure_objects.filter(
        pk=cohort_id, clinic_id=clinic_id
    ).first()
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if cohort is None or course is None:
        raise PermissionDenied
    member_ids = list(
        CohortMember.infrastructure_objects.filter(
            clinic_id=clinic_id, cohort_id=cohort.pk
        ).values_list("user_id", flat=True)
    )
    # Exact-set replay: the same key only replays when every member of this
    # cohort is already enrolled under it — a reused key on a different cohort
    # (or a shrunk cohort) falls through to the normal capacity-checked path.
    replayed_members = set(
        Enrollment.infrastructure_objects.filter(
            clinic_id=clinic_id,
            course_id=course.pk,
            idempotency_key=idempotency_key,
        ).values_list("user_id", flat=True)
    )
    if len(member_ids) > 0 and set(member_ids).issubset(replayed_members):
        return list(
            Enrollment.infrastructure_objects.filter(
                clinic_id=clinic_id,
                course_id=course.pk,
                user_id__in=member_ids,
                idempotency_key=idempotency_key,
            )
        )
    _require_course_access(clinic_id=clinic_id, course=course, now=timezone.now())
    active = Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id, course_id=course.pk, ended_at__isnull=True
    ).count()
    seats = None if course.capacity is None else max(course.capacity - active, 0)
    if seats is not None and seats < len(member_ids):
        raise ValidationError("A coorte excede as vagas disponíveis deste curso.")
    enrollments: list[Enrollment] = []
    for member_id in member_ids:
        enrollment, created = Enrollment.infrastructure_objects.get_or_create(
            clinic_id=clinic_id,
            course_id=course.pk,
            user_id=member_id,
            defaults={
                "source": EnrollmentSource.COHORT,
                "idempotency_key": idempotency_key,
            },
        )
        if created:
            record_audit_event(
                clinic_id=clinic_id,
                actor_id=actor.pk,
                action="create",
                resource_type="enrollment",
                resource_id=str(enrollment.pk),
                outcome="success",
                request_id=idempotency_key,
                network_origin=None,
            )
        enrollments.append(enrollment)
    return enrollments


@transaction.atomic
def end_enrollment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    enrollment_id: UUID,
    reason: str,
    request_id: UUID,
) -> Enrollment:
    """End one active enrollment with an audited, required justification."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    enrollment = (
        Enrollment.infrastructure_objects.select_for_update()
        .filter(pk=enrollment_id, clinic_id=clinic_id)
        .first()
    )
    if enrollment is None:
        raise PermissionDenied
    if enrollment.ended_at is not None:
        raise ValidationError("Esta matrícula já foi encerrada.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValidationError("Informe o motivo do encerramento da matrícula.")
    enrollment.ended_at = timezone.now()
    enrollment.end_reason = clean_reason
    enrollment.save(update_fields=("ended_at", "end_reason", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="enrollment",
        resource_id=str(enrollment.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return enrollment  # type: ignore[no-any-return]


@transaction.atomic
def complete_lesson(
    *, clinic_id: UUID, user: AbstractBaseUser, lesson_id: UUID, request_id: UUID
) -> LessonCompletion:
    """Record one server-owned lesson completion for an enrolled learner."""
    from clinics.services import ClinicMembership

    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id
    ).first()
    if lesson is None:
        raise PermissionDenied
    if lesson.status != CourseStatus.PUBLISHED:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if not Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=lesson.module.course_id,
        user_id=user.pk,
        ended_at__isnull=True,
    ).exists():
        raise PermissionDenied
    completion, created = LessonCompletion.infrastructure_objects.get_or_create(
        clinic_id=clinic_id, lesson_id=lesson.pk, user_id=user.pk
    )
    if created:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=user.pk,
            action="create",
            resource_type="lesson_completion",
            resource_id=str(completion.pk),
            outcome="success",
            request_id=request_id,
            network_origin=None,
        )
    return completion  # type: ignore[no-any-return]


@transaction.atomic
def issue_certificate(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    user_id: UUID,
    request_id: UUID,
) -> Certificate:
    """Issue one idempotent certificate after server-verified completion."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        raise PermissionDenied
    if not Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user_id,
        ended_at__isnull=True,
    ).exists():
        raise PermissionDenied
    if not _course_is_completed(
        clinic_id=clinic_id, course_id=course.pk, user_id=user_id
    ):
        raise PermissionDenied
    existing = (
        Certificate.infrastructure_objects.filter(
            clinic_id=clinic_id, course_id=course.pk, user_id=user_id
        )
        .order_by("created_at")
        .last()
    )
    if existing is not None and existing.revoked_at is None:
        return existing  # type: ignore[no-any-return]
    code = secrets.token_urlsafe(30)
    while Certificate.infrastructure_objects.filter(public_code=code).exists():
        code = secrets.token_urlsafe(30)
    certificate = Certificate.infrastructure_objects.create(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user_id,
        public_code=code,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="certificate",
        resource_id=str(certificate.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return certificate  # type: ignore[no-any-return]


def _course_is_completed(*, clinic_id: UUID, course_id: UUID, user_id: UUID) -> bool:
    total = Lesson.infrastructure_objects.filter(
        clinic_id=clinic_id, module__course_id=course_id
    ).count()
    completed = LessonCompletion.infrastructure_objects.filter(
        clinic_id=clinic_id, lesson__module__course_id=course_id, user_id=user_id
    ).count()
    return total > 0 and total == completed


@transaction.atomic
def issue_certificate_for_participant(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    course_id: UUID,
    request_id: UUID,
) -> Certificate:
    """Issue one idempotent certificate to the enrolled participant themselves."""
    lock_clinic_for_update(clinic_id=clinic_id)
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        raise PermissionDenied
    if not Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user.pk,
        ended_at__isnull=True,
    ).exists():
        raise PermissionDenied
    if not _course_is_completed(
        clinic_id=clinic_id, course_id=course.pk, user_id=user.pk
    ):
        raise ValidationError("Conclua todas as aulas antes de emitir o certificado.")
    existing = (
        Certificate.infrastructure_objects.filter(
            clinic_id=clinic_id, course_id=course.pk, user_id=user.pk
        )
        .order_by("created_at")
        .last()
    )
    if existing is not None and existing.revoked_at is None:
        return existing  # type: ignore[no-any-return]
    code = secrets.token_urlsafe(30)
    while Certificate.infrastructure_objects.filter(public_code=code).exists():
        code = secrets.token_urlsafe(30)
    certificate = Certificate.infrastructure_objects.create(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=user.pk,
        public_code=code,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create",
        resource_type="certificate",
        resource_id=str(certificate.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return certificate  # type: ignore[no-any-return]


def verify_certificate(public_code: str) -> dict[str, str]:
    """Return the public verification status of one certificate code."""
    certificate = Certificate.infrastructure_objects.filter(
        public_code=public_code
    ).first()
    if certificate is None:
        return {"status": "unknown"}
    if certificate.revoked_at is not None:
        return {"status": "revoked"}
    return {"status": "valid"}


@transaction.atomic
def revoke_certificate(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    certificate_id: UUID,
    reason: str,
    request_id: UUID,
) -> Certificate:
    """Revoke one certificate with an audited, required justification."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    certificate = (
        Certificate.infrastructure_objects.select_for_update()
        .filter(pk=certificate_id, clinic_id=clinic_id)
        .first()
    )
    if certificate is None:
        raise PermissionDenied
    if certificate.revoked_at is not None:
        raise ValidationError("Este certificado já está revogado.")
    if not reason.strip():
        raise ValidationError("Informe o motivo da revogação.")
    certificate.revoked_at = timezone.now()
    certificate.revocation_reason = reason.strip()
    certificate.save(update_fields=("revoked_at", "revocation_reason", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="certificate",
        resource_id=str(certificate.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return certificate  # type: ignore[no-any-return]


def _require_quiz_participant(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    quiz: Quiz,
) -> None:
    """Authorize an enrolled, active member against a published quiz chain."""
    from clinics.services import ClinicMembership

    course = Course.infrastructure_objects.filter(
        pk=quiz.course_id, clinic_id=clinic_id
    ).first()
    if (
        course is None
        or course.status != CourseStatus.PUBLISHED
        or quiz.status != QuizStatus.PUBLISHED
    ):
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if not Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=quiz.course_id,
        user_id=user.pk,
        ended_at__isnull=True,
    ).exists():
        raise PermissionDenied


def quiz_questions_for_participant(
    *, clinic_id: UUID, user: AbstractBaseUser, quiz_id: UUID, seed: int
) -> list[dict[str, object]]:
    """Return a participant-safe projection of tenant quiz questions."""
    quiz = Quiz.infrastructure_objects.filter(pk=quiz_id, clinic_id=clinic_id).first()
    if quiz is None:
        raise PermissionDenied
    _require_quiz_participant(clinic_id=clinic_id, user=user, quiz=quiz)
    questions = list(
        QuizQuestion.infrastructure_objects.filter(clinic_id=clinic_id, quiz=quiz)
    )
    if quiz.shuffle_questions:
        questions.sort(key=lambda question: question.position)
        deterministic = random.Random(seed)
        deterministic.shuffle(questions)
    return [
        {
            "question_id": str(question.pk),
            "prompt": question.prompt,
            "options": question.options,
        }
        for question in questions
    ]


@transaction.atomic
def submit_quiz_attempt(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    quiz_id: UUID,
    answers: dict[str, str],
    request_id: UUID,
    shuffle_seed: int = 0,
) -> QuizAttempt:
    """Grade one educational attempt and enforce the attempt budget."""

    lock_clinic_for_update(clinic_id=clinic_id)
    quiz = Quiz.infrastructure_objects.filter(pk=quiz_id, clinic_id=clinic_id).first()
    if quiz is None:
        raise PermissionDenied
    _require_quiz_participant(clinic_id=clinic_id, user=user, quiz=quiz)
    questions = list(
        QuizQuestion.infrastructure_objects.filter(clinic_id=clinic_id, quiz=quiz)
    )
    if not questions:
        raise ValidationError("Esta avaliação ainda não tem perguntas.")
    replayed = QuizAttempt.infrastructure_objects.filter(
        clinic_id=clinic_id,
        quiz_id=quiz.pk,
        user_id=user.pk,
        request_id=request_id,
    ).first()
    if replayed is not None:
        return replayed  # type: ignore[no-any-return]
    previous_attempts = QuizAttempt.infrastructure_objects.filter(
        clinic_id=clinic_id, quiz=quiz, user_id=user.pk
    ).count()
    if previous_attempts >= quiz.max_attempts:
        raise ValidationError("Número máximo de tentativas alcançado.")
    projection = quiz_questions_for_participant(
        clinic_id=clinic_id, user=user, quiz_id=quiz.pk, seed=shuffle_seed
    )
    question_order = [str(item["question_id"]) for item in projection]
    option_order: dict[str, list[str]] = {}
    for item in projection:
        options = cast(list[dict[str, object]], item["options"])
        option_order[str(item["question_id"])] = [
            str(option["key"]) for option in options
        ]
    correct = 0
    for question in questions:
        if str(answers.get(str(question.pk), "")) == question.correct_key:
            correct += 1
    score = round((correct / len(questions)) * 100)
    attempt = QuizAttempt.infrastructure_objects.create(
        clinic_id=clinic_id,
        quiz_id=quiz.pk,
        user_id=user.pk,
        score=score,
        passed=score >= quiz.minimum_grade,
        answers=dict(answers),
        request_id=request_id,
        shuffle_seed=shuffle_seed,
        question_order=question_order,
        option_order=option_order,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create",
        resource_type="quiz_attempt",
        resource_id=str(attempt.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return attempt  # type: ignore[no-any-return]


def quiz_attempt_feedback(
    *, clinic_id: UUID, user: AbstractBaseUser, attempt_id: UUID
) -> list[dict[str, object]]:
    """Return educational-only explanatory feedback for one own attempt."""
    from clinics.services import ClinicMembership

    attempt = QuizAttempt.infrastructure_objects.filter(
        pk=attempt_id, clinic_id=clinic_id
    ).first()
    if attempt is None:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if attempt.user_id != user.pk:
        raise PermissionDenied
    feedback: list[dict[str, object]] = []
    for question in QuizQuestion.infrastructure_objects.filter(
        clinic_id=clinic_id, quiz_id=attempt.quiz_id
    ):
        selected = attempt.answers.get(str(question.pk), "")
        feedback.append(
            {
                "question_id": str(question.pk),
                "selected": selected,
                "correct": selected == question.correct_key,
                "expected_key": question.correct_key,
                "explanation": question.explanation,
            }
        )
    return feedback


@transaction.atomic
def record_learning_event(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    lesson_id: UUID,
    client_event_id: UUID,
    kind: str,
    position_seconds: int,
    active_seconds: int,
    user_initiated: bool,
    request_id: UUID,
) -> LearningEvent:
    """Store one deduplicated learning event and consolidate progress."""
    from clinics.services import ClinicMembership

    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id
    ).first()
    if lesson is None:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if not Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=lesson.module.course_id,
        user_id=user.pk,
        ended_at__isnull=True,
    ).exists():
        raise PermissionDenied
    if kind not in {"position", "complete", "pause"}:
        raise ValidationError("Tipo de evento de aprendizagem inválido.")
    event, created = LearningEvent.infrastructure_objects.get_or_create(
        clinic_id=clinic_id,
        user_id=user.pk,
        client_event_id=client_event_id,
        defaults={
            "lesson_id": lesson.pk,
            "kind": kind,
            "position_seconds": position_seconds,
            "active_seconds": active_seconds,
            "user_initiated": user_initiated,
        },
    )
    if not created:
        # Idempotent replay: return the original event without double-counting.
        return event  # type: ignore[no-any-return]
    progress = LessonProgress.infrastructure_objects.get_or_create(
        clinic_id=clinic_id, lesson_id=lesson.pk, user_id=user.pk
    )[0]
    if user_initiated:
        progress.total_active_seconds = (
            progress.total_active_seconds or 0
        ) + active_seconds
        if kind == "position":
            progress.last_position_seconds = max(
                progress.last_position_seconds or 0, position_seconds
            )
    progress.save(
        update_fields=("total_active_seconds", "last_position_seconds", "updated_at")
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create",
        resource_type="learning_event",
        resource_id=str(event.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return event  # type: ignore[no-any-return]


def lesson_progress(
    *, clinic_id: UUID, user: AbstractBaseUser, lesson_id: UUID
) -> LessonProgress:
    """Return the consolidated progress for one own lesson."""
    from clinics.services import ClinicMembership

    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id
    ).first()
    if lesson is None:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    progress = LessonProgress.infrastructure_objects.filter(
        clinic_id=clinic_id, lesson_id=lesson.pk, user_id=user.pk
    ).first()
    if progress is None:
        progress = LessonProgress.infrastructure_objects.create(
            clinic_id=clinic_id, lesson_id=lesson.pk, user_id=user.pk
        )
    progress.completed = LessonCompletion.infrastructure_objects.filter(
        clinic_id=clinic_id, lesson_id=lesson.pk, user_id=user.pk
    ).exists()
    return progress  # type: ignore[no-any-return]


@transaction.atomic
def media_playback_grant(
    *, clinic_id: UUID, user: AbstractBaseUser, media_id: UUID
) -> PrivateDownloadGrant:
    """Issue a tenant-bound short-lived grant for one authorized media."""
    from clinics.services import ClinicMembership

    media = ContentMedia.infrastructure_objects.filter(
        pk=media_id, clinic_id=clinic_id
    ).first()
    if media is None:
        raise PermissionDenied
    membership = (
        ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .first()
    )
    if membership is None:
        raise PermissionDenied
    is_editor = membership.role == ClinicMembership.Role.CLINIC_ADMIN
    if not is_editor:
        # Patients may only open media attached to published content that was
        # recommended to them (course-media linkage lands with the player task).
        if media.content.status != ContentStatus.PUBLISHED:
            raise PermissionDenied
        has_recommendation = ContentRecommendation.infrastructure_objects.filter(
            clinic_id=clinic_id,
            content_id=media.content_id,
            status="active",
            patient_id=user.pk,
        ).exists()
        if not has_recommendation:
            raise PermissionDenied
    grant = PrivateDownloadGrant.issue(
        object_key=media.file.name, tenant_id=str(clinic_id)
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="read",
        resource_type="content_media_grant",
        resource_id=str(media.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return grant


@transaction.atomic
def toggle_favorite(
    *, clinic_id: UUID, user: AbstractBaseUser, lesson_id: UUID, favorite: bool
) -> LessonFavorite:
    """Activate or deactivate one lesson favorite for the learner."""
    from clinics.services import ClinicMembership

    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id
    ).first()
    if lesson is None:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    favorite_row, created = LessonFavorite.infrastructure_objects.get_or_create(
        clinic_id=clinic_id,
        lesson_id=lesson.pk,
        user_id=user.pk,
        defaults={"active": favorite},
    )
    if favorite_row.active != favorite:
        favorite_row.active = favorite
        favorite_row.save(update_fields=("active", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create" if created else "update",
        resource_type="lesson_favorite",
        resource_id=str(favorite_row.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return favorite_row  # type: ignore[no-any-return]


@transaction.atomic
def save_private_note(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    lesson_id: UUID,
    note_id: UUID | None,
    body: str,
    request_id: UUID,
) -> PrivateNote:
    """Create or update one own private note for a lesson."""
    from clinics.services import ClinicMembership

    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id
    ).first()
    if lesson is None:
        raise PermissionDenied
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    stripped = body.strip()
    if not stripped:
        raise ValidationError("A anotação não pode ficar vazia.")
    if note_id is None:
        note = PrivateNote.infrastructure_objects.create(
            clinic_id=clinic_id, lesson_id=lesson.pk, author_id=user.pk, body=stripped
        )
        return note  # type: ignore[no-any-return]
    note = PrivateNote.infrastructure_objects.filter(
        pk=note_id, clinic_id=clinic_id, author_id=user.pk
    ).first()
    if note is None:
        raise PermissionDenied
    note.body = stripped
    note.save(update_fields=("body", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="update",
        resource_type="private_note",
        resource_id=str(note.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return note  # type: ignore[no-any-return]


def export_learning_data(
    *, clinic_id: UUID, user: AbstractBaseUser
) -> dict[str, list[dict[str, object]]]:
    """Export the learner's own favorites and private notes."""
    favorites = [
        {"lesson_id": str(row.lesson_id), "active": row.active}
        for row in LessonFavorite.infrastructure_objects.filter(
            clinic_id=clinic_id, user_id=user.pk, active=True
        )
    ]
    notes = [
        {"lesson_id": str(row.lesson_id), "body": row.body}
        for row in PrivateNote.infrastructure_objects.filter(
            clinic_id=clinic_id, author_id=user.pk
        )
    ]
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="export",
        resource_type="learning_data",
        resource_id=str(user.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return {"favorites": favorites, "notes": notes}


@transaction.atomic
def delete_learning_data(*, clinic_id: UUID, user: AbstractBaseUser) -> None:
    """Delete the learner's favorites and private notes for one clinic."""
    LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic_id, user_id=user.pk
    ).delete()
    PrivateNote.infrastructure_objects.filter(
        clinic_id=clinic_id, author_id=user.pk
    ).delete()
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="delete",
        resource_type="learning_data",
        resource_id=str(user.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )


@transaction.atomic
def delete_learning_data_for_subject(*, clinic_id: UUID, subject_id: UUID) -> None:
    """Erase one subject's favorites and private notes for a DSAR erasure.

    Subject-id based so the privacy lifecycle can invoke it without a concrete
    user instance; tenant-scoped and audited like the actor-facing variant.
    """
    LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic_id, user_id=subject_id
    ).delete()
    PrivateNote.infrastructure_objects.filter(
        clinic_id=clinic_id, author_id=subject_id
    ).delete()
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=subject_id,
        action="delete",
        resource_type="learning_data",
        resource_id=str(subject_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )


def retire_recommendations_for_archived_content(
    *, clinic_id: UUID, content: Content
) -> int:
    """Cascade-retire active recommendations when their content is archived."""
    active = ContentRecommendation.infrastructure_objects.filter(
        clinic_id=clinic_id, content_id=content.pk, status="active"
    )
    now = timezone.now()
    count = 0
    for recommendation in active:
        recommendation.status = "retired"
        recommendation.retired_reason = "content_archived"
        recommendation.retired_at = now
        recommendation.save(
            update_fields=("status", "retired_reason", "retired_at", "updated_at")
        )
        notify_recommendation_change(
            clinic_id=clinic_id,
            recommendation=recommendation,
            kind="retired",
            reason="content_archived",
        )
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=None,
            action="update",
            resource_type="content_recommendation",
            resource_id=str(recommendation.pk),
            outcome="success",
            request_id=uuid4(),
            network_origin=None,
        )
        count += 1
    return count


@transaction.atomic
def retire_recommendation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    recommendation_id: UUID,
    reason: str,
    request_id: UUID,
) -> ContentRecommendation:
    """Retire one recommendation with a required audited justification."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    recommendation: ContentRecommendation | None = (
        ContentRecommendation.infrastructure_objects.select_for_update()
        .filter(pk=recommendation_id, clinic_id=clinic_id)
        .first()
    )
    if recommendation is None:
        raise PermissionDenied
    if recommendation.status == "retired":
        raise ValidationError("Esta recomendação já está retirada.")
    if not reason.strip():
        raise ValidationError("Informe o motivo da retirada.")
    recommendation.status = "retired"
    recommendation.retired_reason = reason.strip()
    recommendation.retired_at = timezone.now()
    recommendation.save(
        update_fields=("status", "retired_reason", "retired_at", "updated_at")
    )
    notify_recommendation_change(
        clinic_id=clinic_id,
        recommendation=recommendation,
        kind="retired",
        reason=reason.strip(),
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content_recommendation",
        resource_id=str(recommendation.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return recommendation


def notify_recommendation_change(
    *,
    clinic_id: UUID,
    recommendation: ContentRecommendation,
    kind: str,
    reason: str = "",
) -> list[ContentNotification]:
    """Persist in-product alerts for every recipient affected by a change."""

    recipient_ids: set[UUID] = set()
    if recommendation.patient_id is not None:
        recipient_ids.add(recommendation.patient_id)
    elif recommendation.cohort_id is not None:
        recipient_ids.update(
            CohortMember.infrastructure_objects.filter(
                clinic_id=clinic_id, cohort_id=recommendation.cohort_id
            ).values_list("user_id", flat=True)
        )
    if not recipient_ids:
        return []
    messages = {
        "active": "Uma recomendação de conteúdo foi atribuída a você.",
        "retired": "Uma recomendação foi retirada.",
        "content_removed": "Um conteúdo recomendado a você não está mais disponível.",
    }
    notifications = [
        ContentNotification.infrastructure_objects.create(
            clinic_id=clinic_id,
            recipient_id=recipient_id,
            notification_kind=(
                "recommendation_active"
                if kind == "active"
                else "recommendation_retired"
            ),
            recommendation=recommendation,
            body=messages[kind],
        )
        for recipient_id in sorted(recipient_ids)
    ]
    return notifications


def recommendations_for_patient(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> list[dict[str, object]]:
    """Return visible recommendations addressed to the requesting patient."""
    from clinics.services import ClinicMembership
    from people.services import ProfessionalProfile

    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    today = timezone.localdate()
    rows = ContentRecommendation.infrastructure_objects.filter(
        clinic_id=clinic_id,
        patient_id=user.pk,
        status="active",
    ).select_related("content", "recommended_by")
    listing: list[dict[str, object]] = []
    for row in rows:
        if row.valid_until is not None and row.valid_until < today:
            continue
        content = row.content
        if content.status != ContentStatus.PUBLISHED:
            continue
        if content.valid_until is not None and content.valid_until < today:
            continue
        if not _credential_verified(clinic_id=clinic_id, user_id=row.recommended_by_id):
            continue
        profile = (
            ProfessionalProfile.objects.for_clinic(clinic_id)
            .filter(user_id=row.recommended_by_id)
            .first()
        )
        recommended_by = profile.full_name if profile is not None else ""
        listing.append(
            {
                "content_slug": content.slug,
                "objective": row.objective,
                "priority": row.priority,
                "recommended_by": recommended_by,
                "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            }
        )
    return listing


def _content_cache_keys(clinic_id: UUID) -> tuple[str, str]:
    return (
        f"content:search-generation:{clinic_id}",
        f"content:search:{clinic_id}",
    )


def invalidate_published_content_cache(clinic_id: UUID) -> None:
    """Drop cached published-content results for one tenant."""
    generation_key, _listing_key = _content_cache_keys(clinic_id)
    try:
        generation = int(cache.get(generation_key, 0))
    except TypeError, ValueError:
        generation = 0
    cache.set(generation_key, generation + 1, None)
    cache.delete_pattern(f"content:search:{clinic_id}:*") if hasattr(
        cache, "delete_pattern"
    ) else cache.delete(f"content:search:{clinic_id}")


def _actor_email(actor: AbstractBaseUser) -> str:
    """Return the canonical e-mail of a concrete project user instance."""
    email = getattr(actor, "email", None)
    if not isinstance(email, str):
        raise PermissionDenied
    return email


MEDIA_MAX_BYTES = 20 * 1024 * 1024
MEDIA_ALLOWED_TYPES = {"image/png", "image/jpeg", "video/mp4", "audio/mpeg"}


class ContentMediaUploadPolicy(PrivateUploadPolicy):
    """Admit editorial images plus video/audio with offset-aware magic bytes.

    MP4 stores the ``ftyp`` brand four bytes in; MPEG audio carries an ID3
    tag at the front or a frame-sync header. The base policy matches with
    ``startswith`` only, which cannot express those layouts, so we extend the
    header check without weakening the size/declaration guarantees.
    """

    max_size = MEDIA_MAX_BYTES
    allowed_types: dict[str, tuple[str, tuple[bytes, ...]]] = {
        ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
        ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
        ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
        ".mp4": ("video/mp4", (b"ftyp",)),
        ".mp3": ("audio/mpeg", (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    }

    def _header_matches(self, header: bytes, signatures: tuple[bytes, ...]) -> bool:
        if signatures == (b"ftyp",):
            return len(header) >= 8 and header[4:8] == b"ftyp"
        return any(header.startswith(signature) for signature in signatures)

    def validate(self, upload: object) -> PrivateUploadMetadata:
        name = getattr(upload, "name", "") or ""
        size = getattr(upload, "size", 0) or 0
        suffix = Path(name).suffix.lower()
        expected = self.allowed_types.get(suffix)
        if expected is None:
            raise ValidationError("Tipo de arquivo não permitido.")
        expected_media_type, signatures = expected
        if getattr(upload, "content_type", None) != expected_media_type:
            raise ValidationError("O tipo declarado do arquivo é inválido.")
        if size <= 0 or size > self.max_size:
            raise ValidationError("O arquivo está vazio ou excede o limite permitido.")
        position = upload.tell()  # type: ignore[attr-defined]
        header = upload.read(16)  # type: ignore[attr-defined]
        upload.seek(position)  # type: ignore[attr-defined]
        if not self._header_matches(header, signatures):
            raise ValidationError(
                "O conteúdo do arquivo não corresponde ao tipo informado."
            )
        return PrivateUploadMetadata(
            safe_name=f"{uuid4().hex}{suffix}",
            detected_media_type=expected_media_type,
            size=size,
        )


# Allowed HTML tags and URL schemes for stored editorial bodies.
_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "em",
        "h2",
        "h3",
        "li",
        "ol",
        "p",
        "pre",
        "strong",
        "ul",
    }
)
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})


def _sanitize_url(value: str | None) -> str:
    """Return a safe URL or an empty string when the scheme is not allowed."""
    if not value:
        return ""
    candidate = value.strip().replace("\\", "/").lower()
    normalized = candidate
    while True:
        decoded = unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    if re.sub(r"[\s\x00-\x1f]", "", normalized).find("javascript:") >= 0:
        return ""
    scheme = normalized.split(":", 1)[0] if ":" in normalized else ""
    if scheme and scheme not in _ALLOWED_SCHEMES:
        return ""
    # HTMLParser decodes entities such as &quot; before we see the value, so a
    # crafted href can already carry quote or angle-bracket characters. No
    # legitimate URL contains those delimiters: keep only the part before the
    # first one so the attribute cannot be broken out of when re-emitted.
    return re.split(r"[\"'<>`]", value.strip(), maxsplit=1)[0].strip()


def sanitize_body(body: str) -> str:
    """Reduce stored bodies to an allowlisted tag/attribute/scheme subset."""
    parser = _SafeHTMLParser()
    parser.feed(body)
    parser.close()
    return "".join(parser.rendered)


class _SafeHTMLParser(html.parser.HTMLParser):
    """Emit only allowlisted tags, attributes and URL schemes."""

    _VOID_TAGS = frozenset({"br"})
    _URL_ATTRIBUTES = frozenset({"href"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rendered: list[str] = []
        self._open: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS:
            return
        attributes: list[str] = []
        for name, value in attrs:
            if name not in self._URL_ATTRIBUTES:
                continue
            safe_value = _sanitize_url(value)
            if safe_value:
                attributes.append(f'{name}="{html.escape(safe_value, quote=True)}"')
        if attributes:
            self.rendered.append(f"<{tag} {' '.join(attributes)}>")
        else:
            self.rendered.append(f"<{tag}>")
        if tag not in self._VOID_TAGS:
            self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS:
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in _ALLOWED_TAGS or tag in self._VOID_TAGS:
            return
        if tag in self._open:
            while self._open:
                open_tag = self._open.pop()
                self.rendered.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def handle_data(self, data: str) -> None:
        self.rendered.append(html.escape(data, quote=False))

    def close(self) -> None:
        super().close()
        while self._open:
            self.rendered.append(f"</{self._open.pop()}>")


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


def _credential_verified(*, clinic_id: UUID, user_id: UUID) -> bool:
    """Return whether a professional currently holds a verified credential."""
    from people.services import ProfessionalCredential, ProfessionalProfile

    profile = (
        ProfessionalProfile.objects.for_clinic(clinic_id)
        .filter(user_id=user_id)
        .first()
    )
    if profile is None:
        return False
    return ProfessionalCredential.objects.filter(
        profile=profile, status=ProfessionalCredential.Status.VERIFIED
    ).exists()


def verified_professional_credential(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> dict[str, str]:
    """Resolve the actor's verified professional credential for one tenant."""
    from people.services import ProfessionalCredential, ProfessionalProfile

    profile = (
        ProfessionalProfile.objects.for_clinic(clinic_id)
        .filter(user_id=actor.pk)
        .first()
    )
    if profile is None:
        raise PermissionDenied
    credential = ProfessionalCredential.objects.filter(profile=profile).first()
    if (
        credential is None
        or credential.status != ProfessionalCredential.Status.VERIFIED
    ):
        raise PermissionDenied
    return {
        "council_name": credential.council_name,
        "council_number": credential.council_number,
        "council_jurisdiction": credential.council_jurisdiction,
        "status": credential.status,
        "full_name": profile.full_name,
    }


def _credential_digest(snapshot: dict[str, str], request_id: UUID) -> str:
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(f"{request_id}:{payload}".encode()).hexdigest()


def _attach_taxonomy(
    *,
    clinic_id: UUID,
    categories: list[str],
    tags: list[str],
) -> dict[str, list[Any]]:
    """Resolve or create managed tenant taxonomy rows for editorial content."""
    category_rows: list[Any] = []
    for name in categories:
        from django.utils.text import slugify

        row = ContentCategory.infrastructure_objects.filter(
            clinic_id=clinic_id, name__iexact=name.strip()
        ).first()
        if row is None:
            row = ContentCategory.infrastructure_objects.create(
                clinic_id=clinic_id, name=name.strip(), slug=slugify(name)
            )
        category_rows.append(row)
    tag_rows: list[Any] = []
    for name in tags:
        from django.utils.text import slugify

        row = ContentTag.infrastructure_objects.filter(
            clinic_id=clinic_id, name__iexact=name.strip()
        ).first()
        if row is None:
            row = ContentTag.infrastructure_objects.create(
                clinic_id=clinic_id, name=name.strip(), slug=slugify(name)
            )
        tag_rows.append(row)
    return {"categories": category_rows, "tags": tag_rows}


@transaction.atomic
def start_content(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    slug: str,
    title: str,
    kind: str,
    body: str,
    language_code: str = "pt-BR",
    category: str = "",
    tags: list[str] | None = None,
    categories: list[str] | None = None,
    audience: str = "patient",
    contraindications: str = "",
    source_reference: str = "",
    valid_until: date | None = None,
    request_id: UUID,
) -> Content:
    """Create one draft content item with its first sanitized version."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized_slug = slug.strip().lower()
    if not normalized_slug or not title.strip():
        raise ValidationError("Informe slug e título do conteúdo.")
    if kind not in ContentKind.values:
        raise ValidationError("Tipo de conteúdo inválido.")
    if audience not in {"patient", "professional"}:
        raise ValidationError("Público inválido.")
    if Content.infrastructure_objects.filter(
        clinic_id=clinic_id, slug=normalized_slug
    ).exists():
        raise ValidationError("Já existe conteúdo com este slug.")
    category_rows = _attach_taxonomy(
        clinic_id=clinic_id,
        categories=list(categories or []),
        tags=list(tags or []),
    )
    content = Content.infrastructure_objects.create(
        clinic_id=clinic_id,
        slug=normalized_slug,
        title=title.strip(),
        kind=kind,
        language_code=language_code,
        category=category.strip(),
        tags=list(tags or []),
        audience=audience,
        contraindications=contraindications.strip(),
        source_reference=source_reference.strip(),
        valid_until=valid_until,
        status=ContentStatus.DRAFT,
        created_by_id=actor.pk,
    )
    for category_row in category_rows["categories"]:
        category_row.content_items.add(content)
    for tag_row in category_rows["tags"]:
        tag_row.content_items.add(content)
    ContentVersion.infrastructure_objects.create(
        clinic_id=clinic_id,
        content_id=content.pk,
        version=1,
        body=sanitize_body(body),
        status=ContentStatus.DRAFT,
        body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def update_content_metadata(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    contraindications: str,
    source_reference: str,
    valid_until: date | None,
    request_id: UUID,
) -> Content:
    """Update clinical metadata of one tenant-local editorial content item."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    content.contraindications = contraindications.strip()
    content.source_reference = source_reference.strip()
    content.valid_until = valid_until
    content.save(
        update_fields=(
            "contraindications",
            "source_reference",
            "valid_until",
            "updated_at",
        )
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def create_content_version(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    body: str,
    scheduled_for: datetime | None = None,
    request_id: UUID,
) -> ContentVersion:
    """Add one new draft version without mutating published history."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = Content.infrastructure_objects.filter(
        pk=content_id, clinic_id=clinic_id
    ).first()
    if content is None:
        raise PermissionDenied
    latest = (
        ContentVersion.infrastructure_objects.filter(content_id=content.pk)
        .order_by("-version")
        .first()
    )
    version = (latest.version + 1) if latest is not None else 1
    new_version = ContentVersion.infrastructure_objects.create(
        clinic_id=clinic_id,
        content_id=content.pk,
        version=version,
        body=sanitize_body(body),
        status=ContentStatus.DRAFT,
        scheduled_for=scheduled_for,
        body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )
    content.current_version = version
    content.status = ContentStatus.DRAFT
    content.save(update_fields=("current_version", "status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="content_version",
        resource_id=str(new_version.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return new_version


@transaction.atomic
def append_editorial_comment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    version: int,
    body: str,
    request_id: UUID,
) -> ContentVersionComment:
    """Append an immutable comment to one tenant-local editorial version."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    target = ContentVersion.infrastructure_objects.filter(
        clinic_id=clinic_id,
        content_id=content_id,
        version=version,
    ).first()
    if target is None:
        raise PermissionDenied
    normalized_body = body.strip()
    if not normalized_body:
        raise ValidationError("Informe o comentário editorial.")
    comment = ContentVersionComment.infrastructure_objects.create(
        clinic_id=clinic_id,
        content_version=target,
        author_id=actor.pk,
        body=normalized_body,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="content_version_comment",
        resource_id=str(comment.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return comment


@transaction.atomic
def submit_for_review(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    request_id: UUID,
) -> Content:
    """Move the current version of one content item into review."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    if content.status not in {ContentStatus.DRAFT, ContentStatus.REVIEW}:
        raise ValidationError("Somente rascunhos podem ir para revisão.")
    content.status = ContentStatus.REVIEW
    content.save(update_fields=("status", "updated_at"))
    ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).update(status=ContentStatus.REVIEW, submitted_by_id=actor.pk)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def approve_content_version(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    opinion: str,
    review_references: list[str] | None = None,
    review_evidence: str = "",
    review_required_specialty: str = "",
    review_valid_days: int | None = None,
    request_id: UUID,
) -> Content:
    """Approve the current version with a signed professional review record."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    credential = verified_professional_credential(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    if content.status != ContentStatus.REVIEW:
        raise ValidationError("Somente conteúdos em revisão podem ser aprovados.")
    current_version = ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).first()
    if current_version is not None and current_version.submitted_by_id == actor.pk:
        raise ValidationError(
            "Aprovação e submissão não podem ser feitas pela mesma pessoa."
        )
    if not opinion.strip():
        raise ValidationError("Informe o parecer da revisão clínica.")
    if review_valid_days is not None and review_valid_days <= 0:
        raise ValidationError("Informe um prazo de validade positivo para a revisão.")
    snapshot = credential
    review_valid_until = (
        timezone.localdate() + timedelta(days=review_valid_days)
        if review_valid_days is not None
        else None
    )
    signed_digest = _credential_digest(
        {**credential, "opinion": opinion.strip()}, request_id
    )
    content.status = ContentStatus.APPROVED
    content.save(update_fields=("status", "updated_at"))
    ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).update(
        status=ContentStatus.APPROVED,
        approved_by_id=actor.pk,
        review_opinion=opinion.strip(),
        review_references=list(review_references or []),
        review_evidence=review_evidence.strip(),
        review_required_specialty=review_required_specialty.strip(),
        review_valid_until=review_valid_until,
        review_signed_digest=signed_digest,
        approver_credential_snapshot=snapshot,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def publish_content_version(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    request_id: UUID,
) -> Content:
    """Publish one approved version, stamping the publication moment."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    if content.status != ContentStatus.APPROVED:
        raise ValidationError("Somente conteúdos aprovados podem ser publicados.")
    scheduled = ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).first()
    if (
        scheduled is not None
        and scheduled.scheduled_for is not None
        and scheduled.scheduled_for > timezone.now()
    ):
        raise ValidationError(
            "A publicação agendada deste conteúdo ainda não pode ocorrer."
        )
    if scheduled is None or not scheduled.review_signed_digest:
        raise ValidationError("Somente revisões assinadas podem ser publicadas.")
    if scheduled.review_valid_until is not None and scheduled.review_valid_until < (
        timezone.localdate()
    ):
        raise ValidationError("A revisão clínica deste conteúdo está vencida.")
    verified_professional_credential(clinic_id=clinic_id, actor=actor)
    if scheduled.approved_by_id == actor.pk:
        raise ValidationError(
            "Publicação e aprovação não podem ser feitas pela mesma pessoa."
        )
    if scheduled.approved_by_id is not None and not _credential_verified(
        clinic_id=clinic_id, user_id=scheduled.approved_by_id
    ):
        raise ValidationError(
            "A credencial do profissional que aprovou este conteúdo não está "
            "mais vigente."
        )
    now = timezone.now()
    content.status = ContentStatus.PUBLISHED
    content.save(update_fields=("status", "updated_at"))
    ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).update(status=ContentStatus.PUBLISHED, published_at=now)
    content_published.send(
        sender=Content,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(content.pk),
        request_id=request_id,
    )
    invalidate_published_content_cache(clinic_id)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def recommend_content(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    patient_id: UUID | None,
    cohort_id: UUID | None,
    objective: str,
    priority: str,
    context: str = "",
    valid_days: int | None = None,
    request_id: UUID,
) -> ContentRecommendation:
    """Attribute published content under a verified professional decision."""
    from clinics.services import ClinicMembership

    if priority.strip() not in {"low", "normal", "high"}:
        raise ValidationError("Informe uma prioridade válida.")
    if not context.strip():
        raise ValidationError("Informe o contexto clínico da recomendação.")
    if valid_days is not None and valid_days <= 0:
        raise ValidationError("Informe um período de validade positivo.")
    credential = verified_professional_credential(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = Content.infrastructure_objects.filter(
        pk=content_id, clinic_id=clinic_id
    ).first()
    if content is None or content.status != ContentStatus.PUBLISHED:
        raise PermissionDenied
    if content.valid_until is not None and content.valid_until < timezone.localdate():
        raise ValidationError("Este conteúdo expirou e não pode mais ser recomendado.")
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=actor.pk, role=ClinicMembership.Role.THERAPIST, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if (
        patient_id is not None
        and not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(
            user_id=patient_id,
            role=ClinicMembership.Role.PATIENT,
            is_active=True,
        )
        .exists()
    ):
        raise PermissionDenied
    if (
        cohort_id is not None
        and not Cohort.infrastructure_objects.filter(
            pk=cohort_id, clinic_id=clinic_id
        ).exists()
    ):
        raise PermissionDenied
    if patient_id is None and cohort_id is None:
        raise ValidationError("Informe o paciente ou a coorte destinatária.")
    valid_until = (
        timezone.localdate() + timedelta(days=valid_days)
        if valid_days is not None
        else None
    )
    credential_digest = _credential_digest(credential, request_id)
    recommendation: ContentRecommendation = (
        ContentRecommendation.infrastructure_objects.create(
            clinic_id=clinic_id,
            content_id=content.pk,
            recommended_by_id=actor.pk,
            patient_id=patient_id,
            cohort_id=cohort_id,
            objective=objective.strip(),
            priority=priority.strip(),
            context=context.strip(),
            valid_until=valid_until,
            status="active",
            credential_snapshot=credential,
            credential_digest=credential_digest,
        )
    )
    notify_recommendation_change(
        clinic_id=clinic_id,
        recommendation=recommendation,
        kind="active",
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="content_recommendation",
        resource_id=str(recommendation.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return recommendation


@transaction.atomic
def rollback_content(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    target_version: int,
    request_id: UUID,
) -> Content:
    """Roll back to a previously published version, re-publishing it."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    target = ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=target_version
    ).first()
    if target is None or target.status != ContentStatus.PUBLISHED:
        raise ValidationError("Só é possível reverter para versão já publicada.")
    content.current_version = target_version
    content.status = ContentStatus.PUBLISHED
    content.save(update_fields=("current_version", "status", "updated_at"))
    invalidate_published_content_cache(clinic_id)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def archive_content(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    request_id: UUID,
    successor_id: UUID | None = None,
) -> Content:
    """Archive one published content item, removing it from indexing.

    An optional published, tenant-local successor may be linked so affected
    patients can be pointed to the replacement (controlled substitution).
    """
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = (
        Content.infrastructure_objects.select_for_update()
        .filter(pk=content_id, clinic_id=clinic_id)
        .first()
    )
    if content is None:
        raise PermissionDenied
    if content.status != ContentStatus.PUBLISHED:
        raise ValidationError("Somente conteúdos publicados podem ser arquivados.")
    if successor_id is not None:
        successor = Content.infrastructure_objects.filter(
            pk=successor_id, clinic_id=clinic_id
        ).first()
        if successor is None:
            raise PermissionDenied
        if successor.status != ContentStatus.PUBLISHED:
            raise ValidationError(
                "O conteúdo substituto deve estar publicado antes do arquivamento."
            )
        content.successor_id = successor.pk
    content.status = ContentStatus.ARCHIVED
    content.save(update_fields=("status", "successor", "updated_at"))
    ContentVersion.infrastructure_objects.filter(
        content_id=content.pk, version=content.current_version
    ).update(status=ContentStatus.ARCHIVED)
    retire_recommendations_for_archived_content(clinic_id=clinic_id, content=content)
    content_archived.send(
        sender=Content,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(content.pk),
        request_id=request_id,
    )
    invalidate_published_content_cache(clinic_id)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content",
        resource_id=str(content.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return content


@transaction.atomic
def report_content(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    content_id: UUID,
    reason: str,
    request_id: UUID,
) -> ContentReport:
    """Record one patient-submitted report against published tenant content."""
    from clinics.services import ClinicMembership

    content = Content.infrastructure_objects.filter(
        pk=content_id, clinic_id=clinic_id
    ).first()
    if content is None:
        raise PermissionDenied
    if content.status != ContentStatus.PUBLISHED:
        raise ValidationError("Somente conteúdos publicados podem ser reportados.")
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValidationError("Informe o motivo da denúncia.")
    report = ContentReport.infrastructure_objects.create(
        clinic_id=clinic_id,
        content_id=content.pk,
        reporter_id=user.pk,
        reason=clean_reason,
        status=ContentReport.Status.OPEN,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="create",
        resource_type="content_report",
        resource_id=str(report.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return report  # type: ignore[no-any-return]


@transaction.atomic
def resolve_content_report(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    report_id: UUID,
    resolution: str,
    note: str,
    request_id: UUID,
) -> ContentReport:
    """Resolve one report with a documented, audited decision (admin only)."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    report = (
        ContentReport.infrastructure_objects.select_for_update()
        .filter(pk=report_id, clinic_id=clinic_id)
        .first()
    )
    if report is None:
        raise PermissionDenied
    if report.status != ContentReport.Status.OPEN:
        raise ValidationError("Esta denúncia já foi resolvida.")
    if resolution not in ContentReport.Status.values:
        raise ValidationError("Resolução inválida.")
    report.status = resolution
    report.resolution_note = note.strip()
    report.resolved_by_id = actor.pk
    report.resolved_at = timezone.now()
    report.save(
        update_fields=(
            "status",
            "resolution_note",
            "resolved_by",
            "resolved_at",
            "updated_at",
        )
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="content_report",
        resource_id=str(report.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return report  # type: ignore[no-any-return]


def review_due_content(*, clinic_id: UUID) -> list[Content]:
    """Return published content whose current signed review has expired."""
    today = timezone.localdate()
    due: list[Content] = []
    for content in Content.infrastructure_objects.filter(
        clinic_id=clinic_id, status=ContentStatus.PUBLISHED
    ):
        version = ContentVersion.infrastructure_objects.filter(
            clinic_id=clinic_id,
            content_id=content.pk,
            version=content.current_version,
        ).first()
        if version is None:
            continue
        if (
            version.review_valid_until is not None
            and version.review_valid_until < today
        ):
            due.append(content)
    return due


def search_published_content(
    *,
    clinic_id: UUID,
    query: str,
    language_code: str = "pt-BR",
    audience: str = "patient",
    category: str = "",
) -> list[Content]:
    """Index only published, valid, language- and audience-matching content."""
    from django.utils import timezone as dj_timezone

    generation_key, listing_key = _content_cache_keys(clinic_id)
    generation = cache.get(generation_key)
    generation_value = int(generation) if generation is not None else None
    cache_suffix = (
        f"{language_code}:{audience}:{query.strip().lower()}:{category.strip().lower()}"
    )
    generation_label = generation_value if generation_value is not None else "cold"
    cache_key = f"{listing_key}:{generation_label}:{cache_suffix}"
    cached = cache.get(cache_key) if generation_value is not None else None
    if isinstance(cached, list):
        return cached

    queryset = Content.infrastructure_objects.filter(
        clinic_id=clinic_id,
        status=ContentStatus.PUBLISHED,
        language_code=language_code,
        audience=audience,
    )
    if category.strip():
        queryset = queryset.filter(
            content_categories__name__iexact=category.strip(),
        ).distinct()
    results: list[Content] = []
    needle = query.strip().lower()
    for item in queryset.order_by("title"):
        if item.valid_until is not None and item.valid_until < dj_timezone.localdate():
            continue
        version = ContentVersion.infrastructure_objects.filter(
            content_id=item.pk, version=item.current_version
        ).first()
        if version is None:
            continue
        if (
            needle
            and needle not in item.title.lower()
            and needle not in version.body.lower()
        ):
            continue
        results.append(item)
    if generation_value is None:
        generation_value = 0
    cache.set(generation_key, generation_value, None)
    cache.set(cache_key, results, 60)
    return results


@transaction.atomic
def attach_media(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    content_id: UUID,
    uploaded: object,
    content_type: str,
    original_name: str,
    request_id: UUID,
) -> ContentMedia:
    """Attach one validated private media asset to a content item."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    content = Content.infrastructure_objects.filter(
        pk=content_id, clinic_id=clinic_id
    ).first()
    if content is None:
        raise PermissionDenied
    if content_type not in MEDIA_ALLOWED_TYPES:
        raise ValidationError("Tipo de mídia não suportado.")
    size = getattr(uploaded, "size", None)
    if size is None:
        raise ValidationError("Não foi possível determinar o tamanho do arquivo.")
    if size > MEDIA_MAX_BYTES:
        raise ValidationError("O arquivo excede o limite de 20 MB.")
    policy = ContentMediaUploadPolicy()
    metadata = policy.validate(uploaded)
    if metadata.detected_media_type != content_type:
        raise ValidationError(
            "O conteúdo do arquivo não corresponde ao tipo informado."
        )
    require_clean_malware_scan(uploaded)  # type: ignore[arg-type]
    media = ContentMedia.infrastructure_objects.create(
        clinic_id=clinic_id,
        content_id=content.pk,
        uploader_id=actor.pk,
        file=uploaded,
        original_name=original_name.strip(),
        content_type=content_type,
        size_bytes=size,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="content_media",
        resource_id=str(media.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return media


@transaction.atomic
def create_course(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    slug: str,
    title: str,
    duration_minutes: int,
    instructor_id: UUID,
    request_id: UUID,
    description: str = "",
) -> Course:
    """Create a tenant-owned draft course with an authorized instructor."""
    from clinics.services import ClinicMembership

    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized_slug = slug.strip().lower()
    if not normalized_slug or not title.strip() or duration_minutes <= 0:
        raise ValidationError("Informe curso e duração válidos.")
    if (
        not ClinicMembership.objects.for_clinic(clinic_id)
        .filter(user_id=instructor_id, is_active=True)
        .exists()
    ):
        raise PermissionDenied
    if Course.infrastructure_objects.filter(
        clinic_id=clinic_id, slug=normalized_slug
    ).exists():
        raise ValidationError("Já existe curso com este slug.")
    course = Course.infrastructure_objects.create(
        clinic_id=clinic_id,
        slug=normalized_slug,
        title=title.strip(),
        description=description.strip(),
        duration_minutes=duration_minutes,
        instructor_id=instructor_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="course",
        resource_id=str(course.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return course  # type: ignore[no-any-return]


@transaction.atomic
def publish_course(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    course_id: UUID,
    request_id: UUID,
) -> Course:
    """Publish one complete curriculum and all ordered children atomically."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    course = (
        Course.infrastructure_objects.select_for_update()
        .filter(pk=course_id, clinic_id=clinic_id)
        .first()
    )
    if course is None:
        raise PermissionDenied
    modules = CourseModule.infrastructure_objects.filter(
        clinic_id=clinic_id, course_id=course.pk
    )
    if not modules.exists():
        raise ValidationError("O curso precisa ter ao menos um módulo.")
    lessons = Lesson.infrastructure_objects.filter(
        clinic_id=clinic_id, module__course_id=course.pk
    )
    if (
        lessons.count() < modules.count()
        or modules.exclude(lessons__isnull=False).exists()
    ):
        raise ValidationError("Cada módulo precisa ter ao menos uma aula.")
    if (
        CourseModule.infrastructure_objects.filter(course_id=course.pk)
        .exclude(clinic_id=clinic_id)
        .exists()
        or Lesson.infrastructure_objects.filter(module__course_id=course.pk)
        .exclude(clinic_id=clinic_id)
        .exists()
    ):
        raise PermissionDenied
    now = timezone.now()
    modules.update(status=CourseStatus.PUBLISHED)
    lessons.update(status=CourseStatus.PUBLISHED)
    LessonMaterial.infrastructure_objects.filter(
        clinic_id=clinic_id, lesson__module__course_id=course.pk
    ).update(status=CourseStatus.PUBLISHED)
    course.status = CourseStatus.PUBLISHED
    course.curriculum_version += 1
    course.published_at = now
    course.save(
        update_fields=("status", "curriculum_version", "published_at", "updated_at")
    )
    path_ids = LearningPathCourse.infrastructure_objects.filter(
        clinic_id=clinic_id, course_id=course.pk
    ).values_list("path_id", flat=True)
    paths = LearningPath.infrastructure_objects.filter(
        clinic_id=clinic_id, pk__in=path_ids
    )
    for path in paths:
        linked_course_ids = LearningPathCourse.infrastructure_objects.filter(
            clinic_id=clinic_id, path_id=path.pk
        ).values_list("course_id", flat=True)
        if (
            not Course.infrastructure_objects.filter(pk__in=linked_course_ids)
            .exclude(status=CourseStatus.PUBLISHED)
            .exists()
        ):
            LearningPath.infrastructure_objects.filter(pk=path.pk).update(
                status=CourseStatus.PUBLISHED
            )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="course",
        resource_id=str(course.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return course  # type: ignore[no-any-return]
