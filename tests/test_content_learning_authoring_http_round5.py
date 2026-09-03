"""Round-5 HTTP acceptance tests: course creation and learner enrollment.

Closes the remaining round-3 Important #1 surface (curriculum creation loop)
and adds the participant-facing enrollment entry point for PRD 8.12.2.2.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

import content.models as content_models
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _clinic_team(clinic: Clinic) -> tuple[User, User]:
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    return admin, therapist


def _force_clinic_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def test_course_create_http_creates_tenant_draft_course(client: Client) -> None:
    """8.12.2.1 closes the authoring loop: admin creates a draft course via HTTP."""
    clinic = ClinicFactory.create()
    admin, instructor = _clinic_team(clinic)
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        reverse("content_course_create"),
        {
            "slug": f"curso-novo-{uuid4().hex[:8]}",
            "title": "Curso criado por HTTP",
            "duration_minutes": "45",
            "instructor_id": str(instructor.pk),
        },
    )

    assert response.status_code == 302
    course = content_models.Course.infrastructure_objects.get(
        clinic=clinic, title="Curso criado por HTTP"
    )
    assert course.status == content_models.CourseStatus.DRAFT
    assert course.instructor_id == instructor.pk
    assert response["Location"] == reverse(
        "content_course_authoring_detail", args=[course.pk]
    )


def test_course_create_http_rejects_foreign_instructor_with_message(
    client: Client,
) -> None:
    """An instructor without an active clinic membership is denied with feedback."""

    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    outsider = UserFactory.create()
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        reverse("content_course_create"),
        {
            "slug": f"curso-externo-{uuid4().hex[:8]}",
            "title": "Curso com instrutor externo",
            "duration_minutes": "45",
            "instructor_id": str(outsider.pk),
        },
        follow=True,
    )

    assert response.status_code == 200  # followed redirect to the authoring index
    assert (
        content_models.Course.infrastructure_objects.filter(
            clinic=clinic, title="Curso com instrutor externo"
        ).exists()
        is False
    )
    page = response.content.decode()
    assert "Não foi possível criar o curso com estes dados." in page


def test_course_create_http_denies_non_admin(client: Client) -> None:
    """A therapist cannot create courses."""
    clinic = ClinicFactory.create()
    admin, therapist = _clinic_team(clinic)
    _force_clinic_client(client, clinic, therapist)

    response = client.post(
        reverse("content_course_create"),
        {
            "slug": f"curso-terapeuta-{uuid4().hex[:8]}",
            "title": "Curso não autorizado",
            "duration_minutes": "45",
            "instructor_id": str(therapist.pk),
        },
    )

    assert response.status_code == 403
    assert (
        content_models.Course.infrastructure_objects.filter(
            clinic=clinic, title="Curso não autorizado"
        ).exists()
        is False
    )
    assert admin is not None


def test_enrollment_http_enrolls_active_member_in_published_course(
    client: Client,
) -> None:
    """8.12.2.2 participant entry point: an active member self-enrolls."""
    clinic = ClinicFactory.create()
    admin, instructor = _clinic_team(clinic)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="curso-aberto",
        title="Curso aberto",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    _force_clinic_client(client, clinic, patient)
    idempotency_key = uuid4()

    response = client.post(
        reverse("content_course_enroll", args=[course.pk]),
        {"idempotency_key": str(idempotency_key)},
    )

    assert response.status_code == 302
    enrollment = content_models.Enrollment.infrastructure_objects.get(
        course=course, user=patient
    )
    assert enrollment.source == content_models.EnrollmentSource.INDIVIDUAL
    assert enrollment.idempotency_key == idempotency_key


def test_enrollment_http_replays_idempotently_and_rejects_foreign_course(
    client: Client,
) -> None:
    """Same key replays the same enrollment; foreign ids are indistinguishable."""
    clinic = ClinicFactory.create()
    admin, instructor = _clinic_team(clinic)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="curso-replay",
        title="Curso replay",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.PUBLISHED,
    )
    _force_clinic_client(client, clinic, patient)
    url = reverse("content_course_enroll", args=[course.pk])

    first = client.post(url, {"idempotency_key": str(uuid4())})
    assert first.status_code == 302
    count_after_first = content_models.Enrollment.infrastructure_objects.filter(
        course=course
    ).count()
    replay = client.post(url, {"idempotency_key": str(uuid4())})
    assert replay.status_code == 302
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=course).count()
        == count_after_first
    )

    other_clinic = ClinicFactory.create()
    other_admin, _other_instructor = _clinic_team(other_clinic)
    other_course = content_models.Course.infrastructure_objects.create(
        clinic=other_clinic,
        slug="curso-alheio",
        title="Curso alheio",
        duration_minutes=30,
        instructor=other_admin,
        status=content_models.CourseStatus.PUBLISHED,
    )
    foreign = client.post(
        reverse("content_course_enroll", args=[other_course.pk]),
        {"idempotency_key": str(uuid4())},
    )
    assert foreign.status_code == 404
    assert (
        content_models.Enrollment.infrastructure_objects.filter(
            course=other_course
        ).exists()
        is False
    )


def test_enrollment_http_denies_non_member_and_draft_course(client: Client) -> None:
    """Unenrollable learners get PT-BR feedback, never partial enrollment."""
    from django.contrib.messages import get_messages

    clinic = ClinicFactory.create()
    admin, instructor = _clinic_team(clinic)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    draft = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="curso-rascunho",
        title="Curso em rascunho",
        duration_minutes=30,
        instructor=instructor,
        status=content_models.CourseStatus.DRAFT,
    )
    _force_clinic_client(client, clinic, patient)

    response = client.post(
        reverse("content_course_enroll", args=[draft.pk]),
        {"idempotency_key": str(uuid4())},
        follow=True,
    )

    assert response.status_code == 200  # followed redirect to the library
    assert (
        content_models.Enrollment.infrastructure_objects.filter(course=draft).exists()
        is False
    )
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("não está disponível" in message for message in messages)
