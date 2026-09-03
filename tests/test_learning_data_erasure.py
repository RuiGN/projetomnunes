"""Acceptance tests for DSAR erasure of learning data (PRD 8.12.3.3)."""

from __future__ import annotations

from uuid import uuid4

import pytest

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from privacy.adapters import DatabaseLifecycleAdapter
from privacy.models import ProcessingDestination
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
        title="Curso",
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
        title="Aula",
        position=1,
        duration_minutes=10,
        status=content_models.CourseStatus.PUBLISHED,
    )


def test_database_adapter_erases_learning_data_on_erasure() -> None:
    """The primary-database erasure destination deletes favorites and notes."""
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

    result = DatabaseLifecycleAdapter().execute(
        clinic_id=clinic.pk,
        subject_id=learner.pk,
        request_type="erasure",
        operation_id=uuid4(),
    )

    assert result.outcome == ProcessingDestination.Status.CONFIRMED
    assert not content_models.LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic.pk, user=learner
    ).exists()
    assert not content_models.PrivateNote.infrastructure_objects.filter(
        clinic_id=clinic.pk, author=learner
    ).exists()


def test_database_adapter_does_not_erase_on_correction() -> None:
    """Non-erasure lifecycle types leave learning data intact."""
    clinic, learner = _learner()
    lesson = _enrolled_lesson(clinic, learner)
    content_services.toggle_favorite(
        clinic_id=clinic.pk, user=learner, lesson_id=lesson.pk, favorite=True
    )

    result = DatabaseLifecycleAdapter().execute(
        clinic_id=clinic.pk,
        subject_id=learner.pk,
        request_type="correction",
        operation_id=uuid4(),
    )

    assert result.outcome == ProcessingDestination.Status.CONFIRMED
    assert content_models.LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic.pk, user=learner
    ).exists()
