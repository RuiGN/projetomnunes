"""Round-3 acceptance tests for PRD 8.12.3 learning experience gaps.

Covers the round-2 Important findings: idempotent duplicate events, lesson
media/transcript/captions linkage, audit symmetry, and DSAR erasure wiring.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

import content.models as content_models
import content.services as content_services
from accounts.models import User
from audit.models import AuditEvent
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


def _enrolled_lesson(clinic: Clinic, learner: User) -> content_models.Lesson:
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug=f"curso-{uuid4().hex[:8]}",
        title="Curso com mídia",
        duration_minutes=15,
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
        title="Aula em vídeo",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.PUBLISHED,
    )


def test_duplicate_learning_event_is_idempotent_not_denied() -> None:
    """8.12.3.2 a replayed client_event_id returns the original event, not 403."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)
    event_id = uuid4()

    first = content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=event_id,
        kind="position",
        position_seconds=120,
        active_seconds=30,
        user_initiated=True,
        request_id=uuid4(),
    )
    replay = content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=event_id,
        kind="position",
        position_seconds=999,
        active_seconds=999,
        user_initiated=True,
        request_id=uuid4(),
    )
    assert replay.pk == first.pk
    assert (
        content_models.LearningEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk, user=learner, lesson=lesson
        ).count()
        == 1
    )


def test_learning_services_emit_audit_events() -> None:
    """8.12.3.3 favorites, events and exports leave an audit trail."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)

    content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )
    content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=uuid4(),
        kind="position",
        position_seconds=10,
        active_seconds=5,
        user_initiated=True,
        request_id=uuid4(),
    )
    content_services.export_learning_data(clinic_id=clinic.pk, user=learner)

    actions = set(
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(actor_id=learner.pk)
        .values_list("action", flat=True)
    )
    assert "create" in actions  # favorite + learning event
    assert "export" in actions  # export_learning_data


def test_lesson_media_transcript_and_captions_are_persisted() -> None:
    """8.12.3.1 a lesson carries transcript, captions and an optional media link."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)

    lesson.transcript = "Transcrição textual completa da aula."
    lesson.captions = "WEBVTT\n\n00:00.000 --> 00:05.000\nLegenda de exemplo."
    lesson.save(update_fields=("transcript", "captions", "updated_at"))

    refreshed = content_models.Lesson.infrastructure_objects.get(pk=lesson.pk)
    assert refreshed.transcript == "Transcrição textual completa da aula."
    assert refreshed.captions.startswith("WEBVTT")


def test_lesson_player_renders_video_with_speed_and_resume(client: Client) -> None:
    """8.12.3.1 the player renders video, speed control and resume contract."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)
    lesson.transcript = "Transcrição textual completa da aula."
    lesson.save(update_fields=("transcript", "updated_at"))
    client.force_login(learner)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(
        reverse("content_lesson_player", args=[lesson.module.course_id, lesson.pk])
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "lesson-player" in html
    assert "Transcrição textual completa da aula." in html
    assert "data-resume-seconds" in html
    assert "playbackRate" in html or "velocidade" in html.lower()


def test_delete_learning_data_removes_favorites_and_notes() -> None:
    """8.12.3.3 erasure removes the learner's favorites and private notes."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)
    content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )
    content_services.save_private_note(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        note_id=None,
        body="Anotação privada.",
        request_id=uuid4(),
    )

    content_services.delete_learning_data(clinic_id=clinic.pk, user=learner)

    assert not content_models.LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic.pk, user=learner
    ).exists()
    assert not content_models.PrivateNote.infrastructure_objects.filter(
        clinic_id=clinic.pk, author=learner
    ).exists()


def test_learning_data_is_tenant_scoped_on_delete() -> None:
    """8.12.3.3 erasure never touches another tenant's learning data."""
    clinic, learner = _learner()
    other_clinic, other_learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)
    other_lesson = _enrolled_lesson(other_clinic, other_learner)
    content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )
    content_services.toggle_favorite(
        clinic_id=other_clinic.pk,
        user=other_learner,
        lesson_id=other_lesson.pk,
        favorite=True,
    )

    content_services.delete_learning_data(clinic_id=clinic.pk, user=learner)

    assert content_models.LessonFavorite.infrastructure_objects.filter(
        clinic_id=other_clinic.pk, user=other_learner
    ).exists()
