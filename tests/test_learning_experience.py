"""Focused acceptance tests for PRD 8.12.3 learning experience."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import override_settings

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


def _enrolled_lesson(clinic: Clinic, learner: User) -> content_models.Lesson:
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=instructor)
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="player",
        title="Curso com mídia",
        duration_minutes=15,
        instructor=instructor,
        status="published",
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
    lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="Aula em vídeo",
        position=1,
        duration_minutes=10,
        status="published",
    )
    return lesson  # type: ignore[no-any-return]


def _clinic_admin(clinic: Clinic) -> User:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return administrator


def test_learning_events_consolidate_progress_and_reject_duplicates() -> None:
    """8.12.3.2 stores idempotent events and consolidates server-side progress."""
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
    assert first.position_seconds == 120

    replay = content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=event_id,
        kind="position",
        position_seconds=200,
        active_seconds=10,
        user_initiated=True,
        request_id=uuid4(),
    )
    assert replay.pk == first.pk

    content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=uuid4(),
        kind="position",
        position_seconds=300,
        active_seconds=45,
        user_initiated=True,
        request_id=uuid4(),
    )
    content_services.record_learning_event(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        client_event_id=uuid4(),
        kind="position",
        position_seconds=400,
        active_seconds=60,
        user_initiated=False,
        request_id=uuid4(),
    )
    progress = content_services.lesson_progress(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk
    )
    assert progress.last_position_seconds == 300
    assert progress.total_active_seconds == 75
    assert progress.completed is False

    content_services.complete_lesson(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, request_id=uuid4()
    )
    progress = content_services.lesson_progress(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk
    )
    assert progress.completed is True

    other_clinic, _ = _learner()
    with pytest.raises(PermissionDenied):
        content_services.lesson_progress(
            clinic_id=other_clinic.pk, user=learner, lesson_id=lesson.pk
        )
    with pytest.raises(PermissionDenied):
        content_services.record_learning_event(
            clinic_id=other_clinic.pk,
            user=learner,
            lesson_id=lesson.pk,
            client_event_id=uuid4(),
            kind="position",
            position_seconds=10,
            active_seconds=1,
            user_initiated=True,
            request_id=uuid4(),
        )


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_media_playback_grant_is_tenant_bound_and_expiring() -> None:
    """8.12.3.1 issues short-lived signed grants for authorized lesson media."""
    from content.models import ContentRecommendation

    clinic, learner = _learner()
    from django.core.files.uploadedfile import SimpleUploadedFile

    content = content_models.Content.infrastructure_objects.create(
        clinic=clinic,
        slug="video-aula",
        title="Vídeo da aula",
        kind=content_models.ContentKind.VIDEO,
        status="published",
        current_version=1,
        created_by=learner,
    )
    upload = SimpleUploadedFile(
        "aula.png", b"\x89PNG\r\n\x1a\nsynthetic", content_type="image/png"
    )
    media = content_services.attach_media(
        clinic_id=clinic.pk,
        actor=_clinic_admin(clinic),
        content_id=content.pk,
        uploaded=upload,
        content_type="image/png",
        original_name="aula.mp4",
        request_id=uuid4(),
    )

    # without an active recommendation the learner cannot open the media yet
    with pytest.raises(PermissionDenied):
        content_services.media_playback_grant(
            clinic_id=clinic.pk, user=learner, media_id=media.pk
        )

    ContentRecommendation.infrastructure_objects.create(
        clinic=clinic,
        content=content,
        recommended_by=_clinic_admin(clinic),
        patient=learner,
        objective="Reforço do plano",
        priority="normal",
        context="Acesso à video-aula.",
        status="active",
    )

    grant = content_services.media_playback_grant(
        clinic_id=clinic.pk, user=learner, media_id=media.pk
    )
    assert grant.token
    resolved = grant.resolve(tenant_id=str(clinic.pk), max_age_seconds=300)
    assert resolved == media.file.name

    other_clinic, _ = _learner()
    with pytest.raises(PermissionDenied):
        content_services.media_playback_grant(
            clinic_id=other_clinic.pk, user=learner, media_id=media.pk
        )


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_media_playback_grant_denies_draft_content_to_patients() -> None:
    """Unpublished media never reaches patients, even with a recommendation."""
    from content.models import ContentRecommendation

    clinic, learner = _learner()
    from django.core.files.uploadedfile import SimpleUploadedFile

    draft = content_models.Content.infrastructure_objects.create(
        clinic=clinic,
        slug="rascunho-video",
        title="Rascunho de vídeo",
        kind=content_models.ContentKind.VIDEO,
        status="draft",
        current_version=1,
        created_by=learner,
    )
    upload = SimpleUploadedFile(
        "rascunho.png", b"\x89PNG\r\n\x1a\nsynthetic", content_type="image/png"
    )
    media = content_services.attach_media(
        clinic_id=clinic.pk,
        actor=_clinic_admin(clinic),
        content_id=draft.pk,
        uploaded=upload,
        content_type="image/png",
        original_name="rascunho.mp4",
        request_id=uuid4(),
    )
    ContentRecommendation.infrastructure_objects.create(
        clinic=clinic,
        content=draft,
        recommended_by=_clinic_admin(clinic),
        patient=learner,
        objective="Não deveria existir",
        priority="normal",
        context="Mídia em rascunho.",
        status="active",
    )
    with pytest.raises(PermissionDenied):
        content_services.media_playback_grant(
            clinic_id=clinic.pk, user=learner, media_id=media.pk
        )


def test_favorites_private_notes_export_and_deletion() -> None:
    """8.12.3.3 keeps per-device sync data exportable and deletable."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)

    favorite = content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )
    assert favorite.active is True
    favorite_again = content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )
    assert favorite_again.pk == favorite.pk

    note = content_services.save_private_note(
        clinic_id=clinic.pk,
        user=learner,
        lesson_id=lesson.pk,
        note_id=None,
        body="Minha anotação privada.",
        request_id=uuid4(),
    )
    assert note.body == "Minha anotação privada."

    exported = content_services.export_learning_data(clinic_id=clinic.pk, user=learner)
    favorite_ids = [str(item["lesson_id"]) for item in exported["favorites"]]
    assert favorite_ids == [str(lesson.pk)]
    assert exported["notes"][0]["body"] == "Minha anotação privada."

    content_services.delete_learning_data(clinic_id=clinic.pk, user=learner)
    exported = content_services.export_learning_data(clinic_id=clinic.pk, user=learner)
    assert exported["favorites"] == []
    assert exported["notes"] == []


def test_lesson_player_template_meets_accessibility_contract() -> None:
    """8.12.3.4 renders a keyboard/captions/transcript accessible player."""
    from django.template import Context, Template

    template = Template(
        "{% include 'content/lesson_player.html' with player=player only %}"
    )
    player = {
        "title": "Aula em vídeo",
        "media_url": "https://media.example.test/aula.mp4",
        "captions_url": "https://media.example.test/aula.vtt",
        "transcript": "Transcrição textual completa da aula.",
        "resume_seconds": 120,
        "duration_minutes": 10,
    }
    html = template.render(Context({"player": player}))

    assert '<track kind="captions"' in html
    assert "sr-only" in html or "aria-label" in html
    assert "Transcrição textual completa da aula." in html
    assert 'data-resume-seconds="120"' in html
    assert "controls" in html
