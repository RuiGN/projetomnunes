"""Round-2 review fix wave: PRD 8.12.2 service-layer regression tests.

Covers Important findings 1-5 from .superpowers/sdd/task-8.12.2-review-round2.md.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, admin


def _patient(clinic: Clinic) -> User:
    user = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=user, role=ClinicMembership.Role.PATIENT
    )
    return user


def _course(
    clinic: Clinic,
    instructor: User,
    slug: str,
    **kw: object,  # noqa: ANN003
) -> content_models.Course:
    course: content_models.Course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug=slug,
        title=slug,
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
        **kw,
    )
    return course


def _quiz(
    clinic: Clinic,
    course: content_models.Course,
    slug: str,
    *,
    status: str = content_models.QuizStatus.PUBLISHED,
) -> content_models.Quiz:
    quiz: content_models.Quiz = content_models.Quiz.infrastructure_objects.create(
        clinic=clinic,
        course=course,
        slug=slug,
        title=slug,
        minimum_grade=70,
        max_attempts=3,
        shuffle_questions=False,
        status=status,
    )
    return quiz


def _question(
    clinic: Clinic,
    quiz: content_models.Quiz,
    key: str = "a",
    position: int = 1,
) -> content_models.QuizQuestion:
    question: content_models.QuizQuestion = (
        content_models.QuizQuestion.infrastructure_objects.create(
            clinic=clinic,
            quiz=quiz,
            prompt="P?",
            options=[{"key": "a", "text": "A"}, {"key": "b", "text": "B"}],
            correct_key=key,
            explanation="Explicação.",
            position=position,
        )
    )
    return question


def _enroll(clinic: Clinic, user: User, course: content_models.Course) -> None:
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=user,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )


def _module_lesson(
    clinic: Clinic,
    course: content_models.Course,
    title: str = "M",
) -> tuple[content_models.CourseModule, content_models.Lesson]:
    module: content_models.CourseModule = (
        content_models.CourseModule.infrastructure_objects.create(
            clinic=clinic, course=course, title=title, position=1
        )
    )
    lesson: content_models.Lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="L",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.PUBLISHED,
    )
    return module, lesson


# ---------------------------------------------------------------------------
# Important 1 — cohort enrollment must respect course capacity
# ---------------------------------------------------------------------------


def test_cohort_enrollment_rejects_cohort_above_capacity() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "coorte-capacidade", capacity=2)
    cohort = content_models.Cohort.infrastructure_objects.create(
        clinic=clinic, name="Coorte cheia"
    )
    for _ in range(3):
        member = _patient(clinic)
        content_models.CohortMember.infrastructure_objects.create(
            clinic=clinic, cohort=cohort, user=member
        )

    with pytest.raises(ValidationError) as excinfo:
        content_services.enroll_cohort(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            cohort_id=cohort.pk,
            idempotency_key=uuid4(),
        )

    assert "vagas" in str(excinfo.value)
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=course).count()
        == 0
    )


def test_cohort_enrollment_allows_cohort_within_capacity() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "coorte-dentro", capacity=3)
    cohort = content_models.Cohort.infrastructure_objects.create(
        clinic=clinic, name="Coorte ok"
    )
    for _ in range(2):
        member = _patient(clinic)
        content_models.CohortMember.infrastructure_objects.create(
            clinic=clinic, cohort=cohort, user=member
        )
    _enroll(clinic, _patient(clinic), course)  # one seat already taken

    content_services.enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=cohort.pk,
        idempotency_key=uuid4(),
    )
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=course).count()
        == 3
    )


# ---------------------------------------------------------------------------
# Important 2 — quiz participant surface is gated and projection is safe
# ---------------------------------------------------------------------------


def test_quiz_questions_require_enrollment_and_published_quiz() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "quiz-gate")
    patient = _patient(clinic)
    quiz = _quiz(clinic, course, "gate")
    _question(clinic, quiz)

    with pytest.raises(PermissionDenied):
        content_services.quiz_questions_for_participant(
            clinic_id=clinic.pk, user=patient, quiz_id=quiz.pk, seed=1
        )

    _enroll(clinic, patient, course)

    draft_quiz = _quiz(clinic, course, "rascunho-gate", status="draft")
    with pytest.raises(PermissionDenied):
        content_services.quiz_questions_for_participant(
            clinic_id=clinic.pk, user=patient, quiz_id=draft_quiz.pk, seed=1
        )

    projection = content_services.quiz_questions_for_participant(
        clinic_id=clinic.pk, user=patient, quiz_id=quiz.pk, seed=1
    )
    assert len(projection) == 1
    assert set(projection[0]) == {"question_id", "prompt", "options"}
    assert all("correct_key" not in str(value) for value in projection[0].values())


def test_quiz_attempt_requires_enrollment_and_is_idempotent_on_retry() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "quiz-idempotente")
    patient = _patient(clinic)
    quiz = _quiz(clinic, course, "avaliacao-id")
    question = _question(clinic, quiz)

    same_request_id = uuid4()
    with pytest.raises(PermissionDenied):
        content_services.submit_quiz_attempt(
            clinic_id=clinic.pk,
            user=patient,
            quiz_id=quiz.pk,
            answers={str(question.pk): "a"},
            request_id=same_request_id,
        )

    _enroll(clinic, patient, course)
    first = content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=patient,
        quiz_id=quiz.pk,
        answers={str(question.pk): "a"},
        request_id=same_request_id,
    )
    replay = content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=patient,
        quiz_id=quiz.pk,
        answers={str(question.pk): "a"},
        request_id=same_request_id,
    )
    assert replay.pk == first.pk
    assert (
        content_models.QuizAttempt.infrastructure_objects.filter(
            quiz=quiz, user=patient
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Important 3 — enrollment idempotent replay returns the original enrollment
# ---------------------------------------------------------------------------


def test_enrollment_replay_same_key_returns_original_enrollment() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "replay-chave")
    patient = _patient(clinic)
    key = uuid4()
    first = content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=patient,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=key,
    )
    replayed = content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=patient,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=key,
    )
    assert replayed.pk == first.pk
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=course).count()
        == 1
    )


def test_enrollment_with_new_key_for_already_enrolled_user_is_rejected() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "replay-nova-chave")
    patient = _patient(clinic)
    _enroll(clinic, patient, course)
    with pytest.raises(ValidationError):
        content_services.enroll_individual(
            clinic_id=clinic.pk,
            user=patient,
            course_id=course.pk,
            plan_codes=set(),
            invitation_id=None,
            idempotency_key=uuid4(),
        )


# ---------------------------------------------------------------------------
# Important 5 — prerequisites are persisted and enforced at enrollment
# ---------------------------------------------------------------------------


def test_learning_path_persists_prerequisites() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "curso-final")
    prerequisite = _course(clinic, admin, "curso-base")

    content_services.create_learning_path(
        clinic_id=clinic.pk,
        actor=admin,
        slug="trilha-pre",
        title="Trilha com pré-requisito",
        courses=[
            {"course_id": str(prerequisite.pk)},
            {
                "course_id": str(course.pk),
                "prerequisite_course_id": str(prerequisite.pk),
            },
        ],
        request_id=uuid4(),
    )

    links = content_models.CoursePrerequisite.infrastructure_objects.filter(
        clinic=clinic, course=course
    )
    assert links.count() == 1
    assert str(links.get().prerequisite_course_id) == str(prerequisite.pk)


def test_enrollment_requires_completed_prerequisites() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "curso-avancado")
    prerequisite = _course(clinic, admin, "curso-intro")
    _, prerequisite_lesson = _module_lesson(clinic, prerequisite)
    content_models.CoursePrerequisite.infrastructure_objects.create(
        clinic=clinic, course=course, prerequisite_course=prerequisite
    )

    patient = _patient(clinic)
    with pytest.raises(ValidationError) as excinfo:
        _enroll(clinic, patient, course)
    assert "pré-requisito" in str(excinfo.value)

    # completing the prerequisite unlocks enrollment
    _enroll(clinic, patient, prerequisite)
    content_services.complete_lesson(
        clinic_id=clinic.pk,
        user=patient,
        lesson_id=prerequisite_lesson.pk,
        request_id=uuid4(),
    )
    _enroll(clinic, patient, course)
    assert (
        content_models.Enrollment.infrastructure_objects.filter(
            course=course, user=patient
        ).exists()
        is True
    )


# ---------------------------------------------------------------------------
# Minor 5 — lesson completion requires a published lesson
# ---------------------------------------------------------------------------


def test_lesson_completion_requires_published_lesson() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "aula-rascunho")
    patient = _patient(clinic)
    _enroll(clinic, patient, course)
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="M", position=1
    )
    draft_lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="L rascunho",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.DRAFT,
    )
    with pytest.raises(PermissionDenied):
        content_services.complete_lesson(
            clinic_id=clinic.pk,
            user=patient,
            lesson_id=draft_lesson.pk,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# Minor 1 — complete_lesson returns the completion record
# ---------------------------------------------------------------------------


def test_complete_lesson_returns_completion_record() -> None:
    clinic, admin = _admin()
    course = _course(clinic, admin, "retorno-conclusao")
    patient = _patient(clinic)
    _enroll(clinic, patient, course)
    _, lesson = _module_lesson(clinic, course)
    completion = content_services.complete_lesson(
        clinic_id=clinic.pk,
        user=patient,
        lesson_id=lesson.pk,
        request_id=uuid4(),
    )
    assert isinstance(completion, content_models.LessonCompletion)
    assert completion.user_id == patient.pk
    assert completion.lesson_id == lesson.pk


# ---------------------------------------------------------------------------
# Important 7 — cohort enrollment is explicitly admin-vouched
# ---------------------------------------------------------------------------


def test_cohort_enrollment_documents_admin_vouching_for_plan_gates() -> None:
    """Admin cohort enrollment vouches for access rules by explicit design."""
    clinic, admin = _admin()
    course = _course(
        clinic, admin, "coorte-vouch", required_plan_code="premium", capacity=5
    )
    cohort = content_models.Cohort.infrastructure_objects.create(
        clinic=clinic, name="Coorte premium"
    )
    member = _patient(clinic)
    content_models.CohortMember.infrastructure_objects.create(
        clinic=clinic, cohort=cohort, user=member
    )

    content_services.enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=cohort.pk,
        idempotency_key=uuid4(),
    )
    assert (
        content_models.Enrollment.infrastructure_objects.filter(
            course=course, user=member
        ).exists()
        is True
    )


def test_cohort_enrollment_replay_requires_exact_member_set() -> None:
    """A key reused on a different cohort never replays foreign enrollments."""
    clinic, admin = _admin()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = _course(clinic, instructor, "coorte-replay")
    first = content_models.Cohort.infrastructure_objects.create(
        clinic=clinic, name="Coorte um"
    )
    second = content_models.Cohort.infrastructure_objects.create(
        clinic=clinic, name="Coorte dois"
    )
    member_one = _patient(clinic)
    member_two = _patient(clinic)
    content_models.CohortMember.infrastructure_objects.create(
        clinic=clinic, cohort=first, user=member_one
    )
    content_models.CohortMember.infrastructure_objects.create(
        clinic=clinic, cohort=second, user=member_two
    )
    key = uuid4()
    content_services.enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=first.pk,
        idempotency_key=key,
    )

    # Same key against a different cohort must NOT replay member_one's row;
    # it proceeds normally and enrolls member_two.
    result = content_services.enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=second.pk,
        idempotency_key=key,
    )
    assert [row.user_id for row in result] == [member_two.pk]
    assert (
        content_models.Enrollment.infrastructure_objects.filter(
            course=course, idempotency_key=key
        ).count()
        == 2
    )

    # Exact replay for the same cohort still returns its enrollments.
    repeated = content_services.enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=second.pk,
        idempotency_key=key,
    )
    assert {row.pk for row in repeated} == {row.pk for row in result}
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=course).count()
        == 2
    )


def test_learning_path_rejects_self_referential_prerequisite() -> None:
    """8.12.2.1 never persists an unsatisfiable self-prerequisite edge."""
    clinic, admin = _admin()
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="auto-requisito",
        title="Curso auto-requisito",
        duration_minutes=30,
        instructor=admin,
        status="draft",
    )
    with pytest.raises(ValidationError):
        content_services.create_learning_path(
            clinic_id=clinic.pk,
            actor=admin,
            slug="trilha-auto",
            title="Trilha auto",
            courses=[
                {
                    "course_id": str(course.pk),
                    "prerequisite_course_id": str(course.pk),
                }
            ],
            request_id=uuid4(),
        )
    assert (
        content_models.CoursePrerequisite.infrastructure_objects.filter(
            course=course
        ).exists()
        is False
    )
