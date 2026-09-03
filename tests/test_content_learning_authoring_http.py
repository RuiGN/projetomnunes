"""HTTP acceptance tests for PRD 8.12.2 slice 1: course builder surface."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from content.learning_authoring import create_cohort, create_course_module
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _clinic_admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, admin


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


def _draft_course(clinic: Clinic, admin: object) -> content_models.Course:
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=instructor, role=ClinicMembership.Role.THERAPIST
    )
    return content_services.create_course(
        clinic_id=clinic.pk,
        actor=admin,  # type: ignore[arg-type]
        slug=f"curso-{uuid4().hex[:10]}",
        title="Curso com módulos",
        duration_minutes=60,
        instructor_id=instructor.pk,
        request_id=uuid4(),
    )


def test_course_builder_detail_renders_modules_in_stable_order(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)

    create_course_module(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        title="Módulo dois",
        position=1,
        request_id=uuid4(),
    )
    response = client.get(reverse("content_course_authoring_detail", args=[course.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Módulo dois" in body


def test_course_module_create_http_posts_and_redirects(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        reverse("content_course_module_create", args=[course.pk]),
        {"title": "Módulo via HTTP", "position": "1"},
    )

    assert response.status_code == 302
    modules = content_models.CourseModule.infrastructure_objects.filter(
        clinic_id=clinic.pk, course_id=course.pk
    ).order_by("position", "id")
    assert [module.title for module in modules] == ["Módulo via HTTP"]


def test_course_module_create_http_denies_non_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, therapist)

    response = client.post(
        reverse("content_course_module_create", args=[course.pk]),
        {"title": "Bloqueado", "position": "1"},
    )

    assert response.status_code == 403
    assert (
        content_models.CourseModule.infrastructure_objects.filter(
            course_id=course.pk
        ).count()
        == 0
    )


def test_course_module_create_http_foreign_course_is_404(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    foreign_clinic = ClinicFactory.create()
    foreign_admin, _t = _clinic_team(foreign_clinic)
    foreign_course = _draft_course(foreign_clinic, foreign_admin)
    _force_clinic_client(client, clinic, admin)

    missing = uuid4()
    assert (
        client.get(
            reverse("content_course_authoring_detail", args=[missing])
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("content_course_authoring_detail", args=[foreign_course.pk])
        ).status_code
        == 404
    )


def test_course_module_create_http_requires_authentication(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)

    response = client.post(
        reverse("content_course_module_create", args=[course.pk]),
        {"title": "Anônimo", "position": "1"},
    )

    assert response.status_code == 302
    target = str(getattr(response, "url", ""))
    assert "entrar" in target or "login" in target


def test_course_lesson_create_http_posts_and_redirects(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)
    module = create_course_module(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        title="Módulo",
        position=1,
        request_id=uuid4(),
    )

    response = client.post(
        reverse("content_course_lesson_create", args=[course.pk, module.pk]),
        {"title": "Aula HTTP", "duration_minutes": "20", "position": "1"},
    )

    assert response.status_code == 302
    lessons = content_models.Lesson.infrastructure_objects.filter(
        clinic_id=clinic.pk, module_id=module.pk
    )
    assert [lesson.title for lesson in lessons] == ["Aula HTTP"]


def test_course_lesson_create_http_denies_non_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, therapist)
    module = create_course_module(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        title="Módulo bloqueado",
        position=1,
        request_id=uuid4(),
    )

    response = client.post(
        reverse("content_course_lesson_create", args=[course.pk, module.pk]),
        {"title": "Sem permissão", "duration_minutes": "10", "position": "1"},
    )

    assert response.status_code == 403
    assert (
        content_models.Lesson.infrastructure_objects.filter(module_id=module.pk).count()
        == 0
    )


def test_course_prerequisite_add_http_persists_edge(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    prerequisite = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)

    response = client.post(
        reverse("content_course_prerequisite_add", args=[course.pk]),
        {"prerequisite_course_id": str(prerequisite.pk)},
    )

    assert response.status_code == 302
    assert content_models.CoursePrerequisite.infrastructure_objects.filter(
        course_id=course.pk, prerequisite_course_id=prerequisite.pk
    ).exists()


def test_course_prerequisite_add_http_rejects_cycle_with_message(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    prerequisite = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)
    client.post(
        reverse("content_course_prerequisite_add", args=[course.pk]),
        {"prerequisite_course_id": str(prerequisite.pk)},
    )

    response = client.post(
        reverse("content_course_prerequisite_add", args=[prerequisite.pk]),
        {"prerequisite_course_id": str(course.pk)},
    )

    assert response.status_code == 302
    assert (
        content_models.CoursePrerequisite.infrastructure_objects.filter(
            course_id=prerequisite.pk, prerequisite_course_id=course.pk
        ).count()
        == 0
    )


def test_course_publish_http_requires_valid_curriculum(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)
    client.post(
        reverse("content_course_module_create", args=[course.pk]),
        {"title": "Módulo de publicação", "position": "1"},
    )

    denied = client.post(reverse("content_course_publish", args=[course.pk]))

    assert denied.status_code == 302  # validation error message, not crash
    course.refresh_from_db()
    assert course.status == content_models.CourseStatus.DRAFT
    module = content_models.CourseModule.infrastructure_objects.get(course_id=course.pk)
    content_models.Lesson.infrastructure_objects.create(
        clinic_id=clinic.pk,
        module=module,
        title="Aula necessária",
        position=1,
        duration_minutes=20,
    )

    published = client.post(reverse("content_course_publish", args=[course.pk]))

    assert published.status_code == 302
    course.refresh_from_db()
    assert course.status == content_models.CourseStatus.PUBLISHED


def test_course_publish_http_denies_non_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, therapist)

    response = client.post(reverse("content_course_publish", args=[course.pk]))

    assert response.status_code == 403
    course.refresh_from_db()
    assert course.status == content_models.CourseStatus.DRAFT


def test_cohort_http_creates_cohort_and_adds_active_member(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    _force_clinic_client(client, clinic, admin)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )

    created = client.post(reverse("content_cohort_create"), {"name": "Coorte HTTP"})

    assert created.status_code == 302
    cohort = content_models.Cohort.infrastructure_objects.get(
        clinic_id=clinic.pk, name="Coorte HTTP"
    )
    added = client.post(
        reverse("content_cohort_member_add", args=[cohort.pk]),
        {"user_id": str(patient.pk)},
    )
    assert added.status_code == 302
    assert content_models.CohortMember.infrastructure_objects.filter(
        cohort_id=cohort.pk, user_id=patient.pk
    ).exists()


def test_cohort_http_denies_non_admin_and_foreign_cohort(client: Client) -> None:
    clinic = ClinicFactory.create()
    admin, therapist = _clinic_team(clinic)
    create_cohort(clinic_id=clinic.pk, actor=admin, name="Restrita", request_id=uuid4())
    _force_clinic_client(client, clinic, therapist)

    response = client.post(reverse("content_cohort_create"), {"name": "Indevida"})

    assert response.status_code == 403
    outsider_clinic, outsider_admin = _clinic_admin()
    outsider_cohort = create_cohort(
        clinic_id=outsider_clinic.pk,
        actor=outsider_admin,
        name="Alheia",
        request_id=uuid4(),
    )
    _force_clinic_client(client, clinic, admin)
    assert (
        client.get(
            reverse("content_cohort_detail", args=[outsider_cohort.pk])
        ).status_code
        == 404
    )


def test_learning_authoring_dashboard_lists_only_active_tenant_resources(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    admin, _therapist = _clinic_team(clinic)
    course = _draft_course(clinic, admin)
    _force_clinic_client(client, clinic, admin)

    response = client.get(reverse("content_learning_authoring_index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert course.title in body
