"""Focused acceptance tests for PRD 8.12.2 learning products."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

import content.models as content_models
import content.services as content_services
from accounts.models import ClinicInvitation, User
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


def test_curriculum_has_stable_ordering_and_coordinated_publication() -> None:
    """8.12.2.1 publishes a complete, ordered tenant curriculum atomically."""
    course_model = content_models.Course
    module_model = content_models.CourseModule
    lesson_model = content_models.Lesson
    path_model = content_models.LearningPath
    path_course_model = content_models.LearningPathCourse
    prerequisite_model = content_models.CoursePrerequisite
    material_model = content_models.LessonMaterial
    create_course = content_services.create_course
    publish_course = content_services.publish_course

    clinic, admin = _admin()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=instructor,
        role=ClinicMembership.Role.THERAPIST,
    )
    course = create_course(
        clinic_id=clinic.pk,
        actor=admin,
        slug="fundamentos",
        title="Fundamentos do autocuidado",
        duration_minutes=90,
        instructor_id=instructor.pk,
        request_id=uuid4(),
    )
    prerequisite = create_course(
        clinic_id=clinic.pk,
        actor=admin,
        slug="introducao",
        title="Introdução",
        duration_minutes=20,
        instructor_id=instructor.pk,
        request_id=uuid4(),
    )
    prerequisite_model.infrastructure_objects.create(
        clinic=clinic, course=course, prerequisite_course=prerequisite
    )
    second_module = module_model.infrastructure_objects.create(
        clinic=clinic, course=course, title="Prática", position=2
    )
    first_module = module_model.infrastructure_objects.create(
        clinic=clinic, course=course, title="Conceitos", position=1
    )
    second_lesson = lesson_model.infrastructure_objects.create(
        clinic=clinic,
        module=first_module,
        title="Respiração",
        position=2,
        duration_minutes=25,
    )
    first_lesson = lesson_model.infrastructure_objects.create(
        clinic=clinic,
        module=first_module,
        title="Introdução",
        position=1,
        duration_minutes=15,
    )
    lesson_model.infrastructure_objects.create(
        clinic=clinic,
        module=second_module,
        title="Exercício",
        position=1,
        duration_minutes=50,
    )
    material_model.infrastructure_objects.create(
        clinic=clinic,
        lesson=first_lesson,
        title="Resumo",
        url="https://example.test/resumo",
        position=2,
    )
    material_model.infrastructure_objects.create(
        clinic=clinic,
        lesson=first_lesson,
        title="Guia",
        url="https://example.test/guia",
        position=1,
    )
    path = path_model.infrastructure_objects.create(
        clinic=clinic, slug="bem-estar", title="Bem-estar"
    )
    path_course_model.infrastructure_objects.create(
        clinic=clinic, path=path, course=course, position=1
    )

    published = publish_course(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        request_id=uuid4(),
    )

    assert published.status == content_models.CourseStatus.PUBLISHED
    assert published.curriculum_version == 1
    assert published.published_at is not None
    assert list(
        module_model.infrastructure_objects.filter(course=course).values_list(
            "title", flat=True
        )
    ) == ["Conceitos", "Prática"]
    assert list(
        lesson_model.infrastructure_objects.filter(module=first_module).values_list(
            "title", flat=True
        )
    ) == [
        "Introdução",
        "Respiração",
    ]
    assert list(
        material_model.infrastructure_objects.filter(lesson=first_lesson).values_list(
            "title", flat=True
        )
    ) == [
        "Guia",
        "Resumo",
    ]
    assert course.duration_minutes == 90
    assert course.instructor_id == instructor.pk
    assert second_lesson.duration_minutes == 25
    link = path_course_model.infrastructure_objects.get(path=path)
    assert link.course_id == course.pk
    assert course_model.infrastructure_objects.get(pk=course.pk).status == "published"


def test_individual_enrollment_enforces_all_access_rules() -> None:
    """8.12.2.2 fails closed across every configured access rule."""
    enrollment_model = content_models.Enrollment
    enroll = content_services.enroll_individual
    clinic, admin = _admin()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = content_services.create_course(
        clinic_id=clinic.pk,
        actor=admin,
        slug="acesso",
        title="Curso restrito",
        duration_minutes=30,
        instructor_id=instructor.pk,
        request_id=uuid4(),
    )
    now = timezone.now()
    content_models.Course.infrastructure_objects.filter(pk=course.pk).update(
        status="published",
        available_from=now - timedelta(hours=1),
        available_until=now + timedelta(hours=1),
        capacity=1,
        required_plan_code="premium",
        invitation_required=True,
    )
    course.refresh_from_db()
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    invitation = ClinicInvitation.infrastructure_objects.create(
        clinic=clinic,
        issuer=admin,
        recipient_email=patient.email,
        initial_role=ClinicMembership.Role.PATIENT,
        token_digest=uuid4().hex + uuid4().hex,
        expires_at=now + timedelta(days=1),
    )

    with pytest.raises(PermissionDenied):
        enroll(
            clinic_id=clinic.pk,
            user=patient,
            course_id=course.pk,
            plan_codes=set(),
            invitation_id=invitation.pk,
            idempotency_key=uuid4(),
        )
    enrollment = enroll(
        clinic_id=clinic.pk,
        user=patient,
        course_id=course.pk,
        plan_codes={"premium"},
        invitation_id=invitation.pk,
        idempotency_key=uuid4(),
    )
    assert enrollment.source == "individual"

    outsider = UserFactory.create()
    with pytest.raises(PermissionDenied):
        enroll(
            clinic_id=clinic.pk,
            user=outsider,
            course_id=course.pk,
            plan_codes={"premium"},
            invitation_id=invitation.pk,
            idempotency_key=uuid4(),
        )
    second_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=second_patient, role=ClinicMembership.Role.PATIENT
    )
    second_invitation = ClinicInvitation.infrastructure_objects.create(
        clinic=clinic,
        issuer=admin,
        recipient_email=second_patient.email,
        initial_role=ClinicMembership.Role.PATIENT,
        token_digest=uuid4().hex + uuid4().hex,
        expires_at=now + timedelta(days=1),
    )
    with pytest.raises(ValidationError):
        enroll(
            clinic_id=clinic.pk,
            user=second_patient,
            course_id=course.pk,
            plan_codes={"premium"},
            invitation_id=second_invitation.pk,
            idempotency_key=uuid4(),
        )
    assert enrollment_model.infrastructure_objects.filter(course=course).count() == 1


def test_enrollment_rejects_course_outside_availability_window() -> None:
    enroll = content_services.enroll_individual
    clinic, admin = _admin()
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="futuro",
        title="Curso futuro",
        duration_minutes=20,
        instructor=admin,
        status="published",
        available_from=timezone.now() + timedelta(days=1),
    )
    with pytest.raises(ValidationError):
        enroll(
            clinic_id=clinic.pk,
            user=patient,
            course_id=course.pk,
            plan_codes=set(),
            invitation_id=None,
            idempotency_key=uuid4(),
        )


def test_cohort_enrollment_is_idempotent_for_all_members() -> None:
    cohort_model = content_models.Cohort
    cohort_member_model = content_models.CohortMember
    enrollment_model = content_models.Enrollment
    enroll_cohort = content_services.enroll_cohort
    clinic, admin = _admin()
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="coorte",
        title="Curso da coorte",
        duration_minutes=20,
        instructor=admin,
        status="published",
        capacity=2,
    )
    cohort = cohort_model.infrastructure_objects.create(clinic=clinic, name="Turma A")
    for _index in range(2):
        patient = UserFactory.create()
        ClinicMembershipFactory.create(
            clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
        )
        cohort_member_model.infrastructure_objects.create(
            clinic=clinic, cohort=cohort, user=patient
        )
    key = uuid4()
    first = enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=cohort.pk,
        idempotency_key=key,
    )
    repeated = enroll_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        cohort_id=cohort.pk,
        idempotency_key=key,
    )
    assert len(first) == len(repeated) == 2
    assert enrollment_model.infrastructure_objects.filter(course=course).count() == 2
    assert {item.source for item in first} == {"cohort"}


def _published_course(
    clinic: Clinic, instructor: User, slug: str
) -> content_models.Course:
    created_course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug=slug,
        title=slug.replace("-", " ").title(),
        duration_minutes=30,
        instructor=instructor,
        status="published",
    )
    return created_course  # type: ignore[no-any-return]


def test_quiz_grading_attempts_shuffle_and_feedback_stay_educational() -> None:
    """8.12.2.3 grades attempts, caps retries, shuffles deterministically."""
    clinic, admin = _admin()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = _published_course(clinic, instructor, "quiz-basico")
    quiz = content_models.Quiz.infrastructure_objects.create(
        clinic=clinic,
        course=course,
        slug="avaliacao",
        title="Avaliação educacional",
        minimum_grade=70,
        max_attempts=3,
        shuffle_questions=True,
        status="published",
    )
    questions = []
    for position in range(1, 5):
        questions.append(
            content_models.QuizQuestion.infrastructure_objects.create(
                clinic=clinic,
                quiz=quiz,
                prompt=f"Pergunta {position}?",
                options=[
                    {"key": "a", "text": "Opção A"},
                    {"key": "b", "text": "Opção B"},
                ],
                correct_key="a",
                explanation="Explicação educacional da resposta.",
                position=position,
            )
        )
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=patient,
        course_id=quiz.course_id,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )

    seeded_first = content_services.quiz_questions_for_participant(
        clinic_id=clinic.pk, user=patient, quiz_id=quiz.pk, seed=7
    )
    seeded_again = content_services.quiz_questions_for_participant(
        clinic_id=clinic.pk, user=patient, quiz_id=quiz.pk, seed=7
    )
    assert [item["question_id"] for item in seeded_first] == [
        item["question_id"] for item in seeded_again
    ]
    assert {item["question_id"] for item in seeded_first} == {
        str(question.pk) for question in questions
    }

    answers = {str(question.pk): "b" for question in questions}
    first_attempt = content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=patient,
        quiz_id=quiz.pk,
        answers=answers,
        request_id=uuid4(),
    )
    assert first_attempt.score == 0
    assert first_attempt.passed is False

    correct_answers = {str(question.pk): "a" for question in questions}
    second_attempt = content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=patient,
        quiz_id=quiz.pk,
        answers=correct_answers,
        request_id=uuid4(),
    )
    assert second_attempt.score == 100
    assert second_attempt.passed is True

    content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=patient,
        quiz_id=quiz.pk,
        answers=correct_answers,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        content_services.submit_quiz_attempt(
            clinic_id=clinic.pk,
            user=patient,
            quiz_id=quiz.pk,
            answers=correct_answers,
            request_id=uuid4(),
        )

    feedback = content_services.quiz_attempt_feedback(
        clinic_id=clinic.pk, user=patient, attempt_id=first_attempt.pk
    )
    assert len(feedback) == len(questions)
    assert all(item["correct"] is False for item in feedback)
    assert {item["explanation"] for item in feedback} == {
        "Explicação educacional da resposta."
    }
    assert set(feedback[0]) == {
        "question_id",
        "selected",
        "correct",
        "expected_key",
        "explanation",
    }

    other_clinic, _ = _admin()
    with pytest.raises(PermissionDenied):
        content_services.quiz_attempt_feedback(
            clinic_id=other_clinic.pk, user=patient, attempt_id=first_attempt.pk
        )


def test_certificate_requires_completion_and_audits_revocation() -> None:
    """8.12.2.4 issues idempotent verifiable certificates with audited revocation."""
    from audit.models import AuditEvent

    clinic, admin = _admin()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = _published_course(clinic, instructor, "certificavel")
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="Módulo único", position=1
    )
    lessons = [
        content_models.Lesson.infrastructure_objects.create(
            clinic=clinic,
            module=module,
            title=f"Aula {position}",
            position=position,
            duration_minutes=10,
            status="published",
        )
        for position in (1, 2)
    ]
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=patient,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        content_services.issue_certificate(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            user_id=patient.pk,
            request_id=uuid4(),
        )

    for lesson in lessons:
        content_services.complete_lesson(
            clinic_id=clinic.pk, user=patient, lesson_id=lesson.pk, request_id=uuid4()
        )

    certificate = content_services.issue_certificate(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        user_id=patient.pk,
        request_id=uuid4(),
    )
    assert len(certificate.public_code) >= 40
    assert certificate.public_code != str(certificate.pk)
    reissued = content_services.issue_certificate(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        user_id=patient.pk,
        request_id=uuid4(),
    )
    assert reissued.pk == certificate.pk
    assert content_services.verify_certificate(certificate.public_code)["status"] == (
        "valid"
    )

    revoked = content_services.revoke_certificate(
        clinic_id=clinic.pk,
        actor=admin,
        certificate_id=certificate.pk,
        reason="Emissão indevida detectada",
        request_id=uuid4(),
    )
    assert revoked.revoked_at is not None
    assert content_services.verify_certificate(certificate.public_code)["status"] == (
        "revoked"
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(resource_type="certificate", resource_id=str(certificate.pk))
        .exists()
    )

    replacement = content_services.issue_certificate(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        user_id=patient.pk,
        request_id=uuid4(),
    )
    assert replacement.pk != certificate.pk
    assert replacement.public_code != certificate.public_code
    assert content_services.verify_certificate(replacement.public_code)["status"] == (
        "valid"
    )
