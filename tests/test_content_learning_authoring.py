"""Service-level acceptance tests for PRD 8.12.2 slice 2: lessons and materials."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

import content.models as content_models
import content.services as content_services
from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from content.learning_authoring import (
    add_cohort_member,
    add_course_prerequisite,
    create_cohort,
    create_course_module,
    create_lesson,
    create_lesson_material,
    create_quiz,
    create_quiz_question,
    publish_quiz,
)
from content.learning_selectors import (
    learning_lesson_materials,
    learning_module_lessons,
)
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


def _draft_course(clinic: Clinic, admin: User) -> content_models.Course:
    instructor = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=instructor,
        role=ClinicMembership.Role.THERAPIST,
    )
    return content_services.create_course(
        clinic_id=clinic.pk,
        actor=admin,
        slug=f"curso-{uuid4().hex[:10]}",
        title="Curso de aulas",
        duration_minutes=60,
        instructor_id=instructor.pk,
        request_id=uuid4(),
    )


def _module(
    clinic: Clinic, admin: User, course: content_models.Course
) -> content_models.CourseModule:
    return create_course_module(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        title="Módulo base",
        position=1,
        request_id=uuid4(),
    )


def test_create_lesson_inserts_at_position_and_shifts_within_module_only() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module_a = _module(clinic, admin, course)
    module_b = create_course_module(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        title="Outro módulo",
        position=2,
        request_id=uuid4(),
    )

    create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module_a.pk,
        title="Aula um",
        duration_minutes=20,
        position=1,
        request_id=uuid4(),
    )
    create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module_a.pk,
        title="Aula dois",
        duration_minutes=15,
        position=2,
        request_id=uuid4(),
    )
    other = create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module_b.pk,
        title="Aula alheia",
        duration_minutes=10,
        position=1,
        request_id=uuid4(),
    )
    create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module_a.pk,
        title="Aula nova no topo",
        duration_minutes=5,
        position=1,
        request_id=uuid4(),
    )

    lessons = learning_module_lessons(clinic_id=clinic.pk, module_id=module_a.pk)
    assert [lesson.title for lesson in lessons] == [
        "Aula nova no topo",
        "Aula um",
        "Aula dois",
    ]
    assert [lesson.position for lesson in lessons] == [1, 2, 3]
    siblings = learning_module_lessons(clinic_id=clinic.pk, module_id=module_b.pk)
    assert [lesson.pk for lesson in siblings] == [other.pk]


def test_create_lesson_rejects_bad_position_duration_and_blank_title() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)

    with pytest.raises(ValidationError, match="posição"):
        create_lesson(
            clinic_id=clinic.pk,
            actor=admin,
            module_id=module.pk,
            title="Posição zero",
            duration_minutes=10,
            position=0,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="duração"):
        create_lesson(
            clinic_id=clinic.pk,
            actor=admin,
            module_id=module.pk,
            title="Duração inválida",
            duration_minutes=0,
            position=1,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="título"):
        create_lesson(
            clinic_id=clinic.pk,
            actor=admin,
            module_id=module.pk,
            title="   ",
            duration_minutes=10,
            position=1,
            request_id=uuid4(),
        )


def test_create_lesson_denies_non_admin_foreign_module_and_published_course() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        create_lesson(
            clinic_id=clinic.pk,
            actor=therapist,
            module_id=module.pk,
            title="Sem permissão",
            duration_minutes=10,
            position=1,
            request_id=uuid4(),
        )
    foreign, foreign_admin = _clinic_admin()
    foreign_course = _draft_course(foreign, foreign_admin)
    foreign_module = _module(foreign, foreign_admin, foreign_course)
    with pytest.raises(PermissionDenied):
        create_lesson(
            clinic_id=clinic.pk,
            actor=admin,
            module_id=foreign_module.pk,
            title="Curso alheio",
            duration_minutes=10,
            position=1,
            request_id=uuid4(),
        )
    assert learning_module_lessons(clinic_id=clinic.pk, module_id=module.pk) == []


def test_create_lesson_material_orders_and_validates_url() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)
    lesson = create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module.pk,
        title="Aula com materiais",
        duration_minutes=25,
        position=1,
        request_id=uuid4(),
    )
    material = create_lesson_material(
        clinic_id=clinic.pk,
        actor=admin,
        lesson_id=lesson.pk,
        title="Artigo de apoio",
        url="https://exemplo.test/apoio",
        position=1,
        request_id=uuid4(),
    )
    materials = learning_lesson_materials(clinic_id=clinic.pk, lesson_id=lesson.pk)
    assert [row.pk for row in materials] == [material.pk]
    with pytest.raises(ValidationError):
        create_lesson_material(
            clinic_id=clinic.pk,
            actor=admin,
            lesson_id=lesson.pk,
            title="Inválido",
            url="nota-uma-url",
            position=2,
            request_id=uuid4(),
        )


def test_curriculum_authoring_rejects_changes_below_published_course() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)
    create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module.pk,
        title="Aula única",
        duration_minutes=30,
        position=1,
        request_id=uuid4(),
    )
    content_services.publish_course(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="rascunho"):
        create_lesson(
            clinic_id=clinic.pk,
            actor=admin,
            module_id=module.pk,
            title="Pós-publicação",
            duration_minutes=5,
            position=2,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="rascunho"):
        create_course_module(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            title="Módulo pós-publicação",
            position=2,
            request_id=uuid4(),
        )


def test_lesson_and_material_creation_are_audited() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)
    lesson = create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module.pk,
        title="Aula auditada",
        duration_minutes=30,
        position=1,
        request_id=uuid4(),
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(resource_type="lesson", resource_id=str(lesson.pk), action="create")
        .exists()
    )


def test_add_course_prerequisite_persists_edge_and_rejects_cycles() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    other = _draft_course(clinic, admin)

    edge = add_course_prerequisite(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        prerequisite_course_id=other.pk,
        request_id=uuid4(),
    )
    replay = add_course_prerequisite(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        prerequisite_course_id=other.pk,
        request_id=uuid4(),
    )
    assert replay.pk == edge.pk
    with pytest.raises(ValidationError, match="si mesmo"):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            prerequisite_course_id=course.pk,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="ciclo"):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=other.pk,
            prerequisite_course_id=course.pk,
            request_id=uuid4(),
        )


def test_add_course_prerequisite_denies_foreign_course_and_non_admin() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    foreign, foreign_admin = _clinic_admin()
    foreign_course = _draft_course(foreign, foreign_admin)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=foreign_course.pk,
            prerequisite_course_id=course.pk,
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=therapist,
            course_id=course.pk,
            prerequisite_course_id=course.pk,
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            prerequisite_course_id=foreign_course.pk,
            request_id=uuid4(),
        )


def test_add_course_prerequisite_rejects_published_course() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    prerequisite = _draft_course(clinic, admin)
    module = _module(clinic, admin, course)
    create_lesson(
        clinic_id=clinic.pk,
        actor=admin,
        module_id=module.pk,
        title="Aula",
        duration_minutes=20,
        position=1,
        request_id=uuid4(),
    )
    content_services.publish_course(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="rascunho"):
        add_course_prerequisite(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            prerequisite_course_id=prerequisite.pk,
            request_id=uuid4(),
        )


def test_create_cohort_requires_admin_and_normalizes_name() -> None:
    clinic, admin = _clinic_admin()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        create_cohort(
            clinic_id=clinic.pk,
            actor=therapist,
            name="Coorte indevida",
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="nome"):
        create_cohort(
            clinic_id=clinic.pk,
            actor=admin,
            name="   ",
            request_id=uuid4(),
        )
    cohort = create_cohort(
        clinic_id=clinic.pk,
        actor=admin,
        name="Turma de outono",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="nome"):
        create_cohort(
            clinic_id=clinic.pk,
            actor=admin,
            name="turma de outono",
            request_id=uuid4(),
        )
    assert cohort.name == "Turma de outono"
    assert cohort.clinic_id == clinic.pk


def test_add_cohort_member_replays_and_requires_active_membership() -> None:
    clinic, admin = _clinic_admin()
    cohort = create_cohort(
        clinic_id=clinic.pk, actor=admin, name="Coorte ativa", request_id=uuid4()
    )
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=patient,
        role=ClinicMembership.Role.PATIENT,
    )
    added = add_cohort_member(
        clinic_id=clinic.pk,
        actor=admin,
        cohort_id=cohort.pk,
        user_id=patient.pk,
        request_id=uuid4(),
    )
    replay = add_cohort_member(
        clinic_id=clinic.pk,
        actor=admin,
        cohort_id=cohort.pk,
        user_id=patient.pk,
        request_id=uuid4(),
    )
    assert replay.pk == added.pk
    outsider = UserFactory.create()
    with pytest.raises(ValidationError, match="vínculo"):
        add_cohort_member(
            clinic_id=clinic.pk,
            actor=admin,
            cohort_id=cohort.pk,
            user_id=outsider.pk,
            request_id=uuid4(),
        )
    foreign, foreign_admin = _clinic_admin()
    create_cohort(
        clinic_id=foreign.pk, actor=foreign_admin, name="Alheia", request_id=uuid4()
    )
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        add_cohort_member(
            clinic_id=clinic.pk,
            actor=therapist,
            cohort_id=cohort.pk,
            user_id=patient.pk,
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        add_cohort_member(
            clinic_id=clinic.pk,
            actor=therapist,
            cohort_id=cohort.pk,
            user_id=patient.pk,
            request_id=uuid4(),
        )


def test_create_quiz_validates_grade_attempts_and_tenant_slug() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    foreign, foreign_admin = _clinic_admin()
    foreign_course = _draft_course(foreign, foreign_admin)

    with pytest.raises(PermissionDenied):
        create_quiz(
            clinic_id=clinic.pk,
            actor=therapist,
            course_id=course.pk,
            slug="quiz-indevido",
            title="Quiz",
            minimum_grade=70,
            max_attempts=3,
            shuffle_questions=False,
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        create_quiz(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=foreign_course.pk,
            slug="quiz-alheio",
            title="Quiz",
            minimum_grade=70,
            max_attempts=3,
            shuffle_questions=False,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="nota mínima"):
        create_quiz(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            slug="quiz-nota",
            title="Quiz",
            minimum_grade=120,
            max_attempts=3,
            shuffle_questions=False,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="tentativas"):
        create_quiz(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            slug="quiz-tentativas",
            title="Quiz",
            minimum_grade=70,
            max_attempts=0,
            shuffle_questions=False,
            request_id=uuid4(),
        )
    quiz = create_quiz(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        slug="avaliacao-educacional",
        title="Avaliacao educacional",
        minimum_grade=70,
        max_attempts=3,
        shuffle_questions=False,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="slug"):
        create_quiz(
            clinic_id=clinic.pk,
            actor=admin,
            course_id=course.pk,
            slug="avaliacao-educacional",
            title="Duplicado",
            minimum_grade=50,
            max_attempts=1,
            shuffle_questions=True,
            request_id=uuid4(),
        )
    assert quiz.status == content_models.QuizStatus.DRAFT


def test_create_quiz_question_orders_and_requires_correct_key_in_options() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    quiz = create_quiz(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        slug="quiz-questoes",
        title="Quiz questões",
        minimum_grade=70,
        max_attempts=2,
        shuffle_questions=False,
        request_id=uuid4(),
    )
    first = create_quiz_question(
        clinic_id=clinic.pk,
        actor=admin,
        quiz_id=quiz.pk,
        prompt="Quanto é 2+2?",
        options={"a": "3", "b": "4"},
        correct_key="b",
        explanation="2+2=4.",
        position=1,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="chave"):
        create_quiz_question(
            clinic_id=clinic.pk,
            actor=admin,
            quiz_id=quiz.pk,
            prompt="Questão inválida",
            options={"a": "1", "b": "2"},
            correct_key="z",
            explanation="",
            position=2,
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="opções"):
        create_quiz_question(
            clinic_id=clinic.pk,
            actor=admin,
            quiz_id=quiz.pk,
            prompt="Uma opção só",
            options={"a": "única"},
            correct_key="a",
            explanation="",
            position=2,
            request_id=uuid4(),
        )
    second = create_quiz_question(
        clinic_id=clinic.pk,
        actor=admin,
        quiz_id=quiz.pk,
        prompt="Questão no topo",
        options={"a": "1", "b": "2"},
        correct_key="a",
        explanation="",
        position=1,
        request_id=uuid4(),
    )
    ordered = content_models.QuizQuestion.infrastructure_objects.filter(
        quiz_id=quiz.pk
    ).order_by("position", "id")
    assert [row.pk for row in ordered] == [second.pk, first.pk]


def test_publish_quiz_requires_question_and_freezes_authoring() -> None:
    clinic, admin = _clinic_admin()
    course = _draft_course(clinic, admin)
    quiz = create_quiz(
        clinic_id=clinic.pk,
        actor=admin,
        course_id=course.pk,
        slug="quiz-publicavel",
        title="Quiz publicável",
        minimum_grade=70,
        max_attempts=2,
        shuffle_questions=False,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="questão"):
        publish_quiz(
            clinic_id=clinic.pk,
            actor=admin,
            quiz_id=quiz.pk,
            request_id=uuid4(),
        )
    create_quiz_question(
        clinic_id=clinic.pk,
        actor=admin,
        quiz_id=quiz.pk,
        prompt="Questão única",
        options={"a": "1", "b": "2"},
        correct_key="a",
        explanation="",
        position=1,
        request_id=uuid4(),
    )
    publish_quiz(
        clinic_id=clinic.pk,
        actor=admin,
        quiz_id=quiz.pk,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="rascunho"):
        create_quiz_question(
            clinic_id=clinic.pk,
            actor=admin,
            quiz_id=quiz.pk,
            prompt="Pós-publicação",
            options={"a": "1", "b": "2"},
            correct_key="a",
            explanation="",
            position=2,
            request_id=uuid4(),
        )
    replay = publish_quiz(
        clinic_id=clinic.pk,
        actor=admin,
        quiz_id=quiz.pk,
        request_id=uuid4(),
    )
    assert replay.status == content_models.QuizStatus.PUBLISHED
