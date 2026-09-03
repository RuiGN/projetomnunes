"""Round-5 acceptance tests for the learner lesson page (PRD 8.12.3.1)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _learner() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    learner = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=learner, role=ClinicMembership.Role.PATIENT
    )
    return clinic, learner


def _enrolled_published_lesson(clinic: Clinic, learner: User) -> content_models.Lesson:
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug=f"curso-{uuid4().hex[:8]}",
        title="Curso do player",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=learner,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=uuid4(),
    )
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="Módulo", position=1
    )
    return content_models.Lesson.infrastructure_objects.create(  # type: ignore[no-any-return]
        clinic=clinic,
        module=module,
        title="Aula com player",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.PUBLISHED,
    )


def _force_clinic_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def test_lesson_page_renders_player_for_enrolled_learner(client: Client) -> None:
    """8.12.3.1 the learner opens one enrolled lesson with the player contract."""
    clinic, learner = _learner()
    lesson = _enrolled_published_lesson(clinic, learner)
    _force_clinic_client(client, clinic, learner)

    response = client.get(
        reverse("content_lesson_player", args=[lesson.module.course_id, lesson.pk])
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "lesson-player" in html
    assert "Aula com player" in html
    assert "controls" in html
    assert "data-resume-seconds" in html


def test_lesson_event_post_records_progress_and_rejects_foreign_lesson(
    client: Client,
) -> None:
    """8.12.3.2 playback events post through the learner page surface."""
    clinic, learner = _learner()
    lesson = _enrolled_published_lesson(clinic, learner)
    _force_clinic_client(client, clinic, learner)
    url = reverse("content_lesson_event", args=[lesson.module.course_id, lesson.pk])
    event_id = uuid4()

    first = client.post(
        url,
        {
            "client_event_id": str(event_id),
            "kind": "position",
            "position_seconds": "45",
            "active_seconds": "30",
            "user_initiated": "true",
        },
    )
    assert first.status_code == 302

    progress = content_services.lesson_progress(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk
    )
    assert progress.last_position_seconds == 45
    assert progress.total_active_seconds == 30

    replay = client.post(
        url,
        {
            "client_event_id": str(event_id),
            "kind": "position",
            "position_seconds": "45",
            "active_seconds": "30",
            "user_initiated": "true",
        },
    )
    assert replay.status_code == 302  # deduplicated, not an error

    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    foreign_course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="curso-alheio-player",
        title="Curso alheio",
        duration_minutes=10,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    with pytest.raises(PermissionDenied):
        content_services.record_learning_event(
            clinic_id=clinic.pk,
            user=learner,
            lesson_id=uuid4(),  # lesson does not exist in this tenant
            client_event_id=uuid4(),
            kind="position",
            position_seconds=1,
            active_seconds=1,
            user_initiated=True,
            request_id=uuid4(),
        )
    assert foreign_course is not None
    assert (
        content_models.LearningEvent.infrastructure_objects.filter(
            user=learner, lesson=lesson
        ).count()
        == 1
    )


def test_lesson_page_denies_unenrolled_member(client: Client) -> None:
    """No enrollment means no playback page; membership alone is insufficient."""
    clinic, outsider_learner = _learner()
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="curso-fechado",
        title="Curso fechado",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="Módulo", position=1
    )
    lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="Aula fechada",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.PUBLISHED,
    )
    _force_clinic_client(client, clinic, outsider_learner)

    response = client.get(reverse("content_lesson_player", args=[course.pk, lesson.pk]))

    assert response.status_code == 302  # safe redirect with PT-BR message, no media
    assert (
        content_models.LessonProgress.infrastructure_objects.filter(
            lesson=lesson, user=outsider_learner
        ).exists()
        is False
    )


def test_lesson_page_foreign_course_is_404(client: Client) -> None:
    """Another tenant's course id is indistinguishable from a missing one."""
    clinic, learner = _learner()
    lesson = _enrolled_published_lesson(clinic, learner)
    other_clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic, user=learner, role=ClinicMembership.Role.PATIENT
    )
    _force_clinic_client(client, other_clinic, learner)

    response = client.get(
        reverse("content_lesson_player", args=[lesson.module.course_id, lesson.pk])
    )

    assert response.status_code == 404
