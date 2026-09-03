"""Round-5 closure tests for participant learning HTTP and lifecycle gaps."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

import content.models as content_models
import content.selectors as content_selectors
import content.services as content_services
from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _member(clinic: Clinic, role: str = ClinicMembership.Role.PATIENT) -> User:
    user = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=user, role=role)
    return user


def _client_for(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def _published_quiz(
    clinic: Clinic, participant: User
) -> tuple[
    content_models.Course, content_models.Quiz, list[content_models.QuizQuestion]
]:
    instructor = _member(clinic, ClinicMembership.Role.THERAPIST)
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug=f"curso-{uuid4().hex[:8]}",
        title="Curso educacional",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=participant,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )
    quiz = content_models.Quiz.infrastructure_objects.create(
        clinic=clinic,
        course=course,
        slug=f"quiz-{uuid4().hex[:8]}",
        title="Avaliação educacional",
        minimum_grade=50,
        max_attempts=3,
        shuffle_questions=True,
        status=content_models.QuizStatus.PUBLISHED,
    )
    questions = [
        content_models.QuizQuestion.infrastructure_objects.create(
            clinic=clinic,
            quiz=quiz,
            prompt=f"Pergunta {position}",
            options=[
                {"key": "a", "text": "Alternativa A"},
                {"key": "b", "text": "Alternativa B"},
                {"key": "c", "text": "Alternativa C"},
            ],
            correct_key="a",
            explanation=f"Explicação reservada {position}",
            position=position,
        )
        for position in range(1, 5)
    ]
    return course, quiz, questions


def test_quiz_attempt_persists_reproducible_question_and_option_order() -> None:
    clinic = ClinicFactory.create()
    participant = _member(clinic)
    _course, quiz, questions = _published_quiz(clinic, participant)
    seed = 8675309

    projection = content_services.quiz_questions_for_participant(
        clinic_id=clinic.pk, user=participant, quiz_id=quiz.pk, seed=seed
    )
    attempt = content_services.submit_quiz_attempt(
        clinic_id=clinic.pk,
        user=participant,
        quiz_id=quiz.pk,
        answers={str(question.pk): "a" for question in questions},
        request_id=uuid4(),
        shuffle_seed=seed,
    )

    assert attempt.shuffle_seed == seed
    assert attempt.question_order == [item["question_id"] for item in projection]
    assert attempt.option_order == {
        str(item["question_id"]): [
            option["key"] for option in cast(list[dict[str, object]], item["options"])
        ]
        for item in projection
    }
    reproduced = content_services.quiz_questions_for_participant(
        clinic_id=clinic.pk,
        user=participant,
        quiz_id=quiz.pk,
        seed=attempt.shuffle_seed,
    )
    assert reproduced == projection


def test_ending_enrollment_updates_active_selector_capacity_and_access() -> None:
    clinic = ClinicFactory.create()
    admin = _member(clinic, ClinicMembership.Role.CLINIC_ADMIN)
    participant = _member(clinic)
    course, quiz, _questions = _published_quiz(clinic, participant)
    course.capacity = 1
    course.save(update_fields=("capacity", "updated_at"))
    enrollment = content_selectors.active_enrollment_for_user(
        clinic_id=clinic.pk, course_id=course.pk, user_id=participant.pk
    )
    assert enrollment is not None

    ended = content_services.end_enrollment(
        clinic_id=clinic.pk,
        actor=admin,
        enrollment_id=enrollment.pk,
        reason="Encerramento solicitado pelo participante",
        request_id=uuid4(),
    )

    assert ended.ended_at is not None
    assert ended.end_reason == "Encerramento solicitado pelo participante"
    assert (
        content_selectors.active_enrollment_for_user(
            clinic_id=clinic.pk, course_id=course.pk, user_id=participant.pk
        )
        is None
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="enrollment", resource_id=str(enrollment.pk), action="update"
        )
        .exists()
    )
    with pytest.raises(PermissionDenied):
        content_services.quiz_questions_for_participant(
            clinic_id=clinic.pk, user=participant, quiz_id=quiz.pk, seed=1
        )

    reenrolled = content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=participant,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )
    assert reenrolled.pk != enrollment.pk
    assert reenrolled.ended_at is None


def test_participant_quiz_http_is_tenant_safe_idempotent_and_accessible(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    participant = _member(clinic)
    _course, quiz, questions = _published_quiz(clinic, participant)
    url = reverse("content_quiz_participate", args=[quiz.pk])

    anonymous = Client().get(url)
    assert anonymous.status_code == 302
    _client_for(client, clinic, participant)
    page = client.get(url)
    assert page.status_code == 200
    html = page.content.decode()
    assert "Avaliação educacional" in html
    assert "não produz diagnóstico" in html
    assert "<fieldset" in html
    assert "<legend" in html
    assert "correct_key" not in html
    assert "Explicação reservada" not in html
    assert 'name="shuffle_seed"' in html
    assert 'name="request_id"' in html

    seed = UUID(page.context["request_id"]).int & ((1 << 63) - 1)
    request_id = page.context["request_id"]
    payload = {
        "request_id": request_id,
        "shuffle_seed": str(seed),
        **{f"answer_{question.pk}": "a" for question in questions},
    }
    submit_url = reverse("content_quiz_submit", args=[quiz.pk])
    first = client.post(submit_url, payload)
    replay = client.post(submit_url, payload)
    assert first.status_code == replay.status_code == 302
    assert first["Location"] == replay["Location"]
    assert (
        content_models.QuizAttempt.infrastructure_objects.filter(
            clinic=clinic, quiz=quiz, user=participant
        ).count()
        == 1
    )

    feedback = client.get(first["Location"])
    assert feedback.status_code == 200
    feedback_html = feedback.content.decode()
    assert "Seu resultado" in feedback_html
    assert "Explicação reservada" in feedback_html
    assert 'role="status"' in feedback_html

    other = _member(clinic)
    _client_for(client, clinic, other)
    assert client.get(first["Location"]).status_code == 404

    foreign_clinic = ClinicFactory.create()
    foreign_member = _member(foreign_clinic)
    _client_for(client, foreign_clinic, foreign_member)
    assert client.get(url).status_code == 404


def test_participant_certificate_http_requires_completion_and_verifies_publicly(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    participant = _member(clinic)
    course, _quiz, _questions = _published_quiz(clinic, participant)
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="Módulo", position=1, status="published"
    )
    lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="Aula",
        position=1,
        duration_minutes=10,
        status="published",
    )
    _client_for(client, clinic, participant)
    url = reverse("content_course_certificate", args=[course.pk])

    pending = client.get(url)
    assert pending.status_code == 200
    assert "Conclua todas as aulas" in pending.content.decode()
    denied = client.post(url, {"request_id": str(uuid4())})
    assert denied.status_code == 302
    assert not content_models.Certificate.infrastructure_objects.filter(
        clinic=clinic, course=course, user=participant
    ).exists()

    content_services.complete_lesson(
        clinic_id=clinic.pk, user=participant, lesson_id=lesson.pk, request_id=uuid4()
    )
    request_id = uuid4()
    issued = client.post(url, {"request_id": str(request_id)})
    replay = client.post(url, {"request_id": str(request_id)})
    assert issued.status_code == replay.status_code == 302
    certificate = content_models.Certificate.infrastructure_objects.get(
        clinic=clinic, course=course, user=participant
    )
    assert len(certificate.public_code) >= 40
    assert str(certificate.pk) not in certificate.public_code

    detail = client.get(url)
    assert detail.status_code == 200
    assert certificate.public_code in detail.content.decode()
    public_url = reverse("content_certificate_verify", args=[certificate.public_code])
    client.logout()
    verification = client.get(public_url)
    assert verification.status_code == 200
    assert "Certificado válido" in verification.content.decode()
    assert participant.email not in verification.content.decode()

    unknown = client.get(reverse("content_certificate_verify", args=["x" * 40]))
    assert unknown.status_code == 404
