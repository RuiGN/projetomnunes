"""Acceptance tests for PRD 8.7.4 and 8.7.5."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import accept_invitation
from clinics.models import Clinic, ClinicMembership
from goals import exercise_services
from goals.exercise_models import (
    ExerciseAssignment,
    ExerciseComment,
    ExerciseExecution,
    ExerciseStatus,
    ExerciseVisibility,
    ResponseFormat,
    TherapeuticExercise,
)
from people import services as people_services
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


class PatientPayload(TypedDict):
    full_name: str
    social_name: str
    birth_date: date
    gender: str
    email: str
    phone: str
    language_code: str
    timezone_name: str
    accessibility_preferences: str
    address: dict[str, object]
    address_purpose: str
    emergency_contact: dict[str, object]
    emergency_contact_purpose: str


def _payload(email: str) -> PatientPayload:
    return {
        "full_name": "Paciente Exemplo",
        "social_name": "",
        "birth_date": date(1990, 1, 1),
        "gender": "undisclosed",
        "email": email,
        "phone": "",
        "language_code": "pt-BR",
        "timezone_name": "America/Sao_Paulo",
        "accessibility_preferences": "",
        "address": {},
        "address_purpose": "",
        "emergency_contact": {},
        "emergency_contact_purpose": "",
    }


def _setup_clinic_therapist_and_patient(
    clinic: Clinic,
) -> tuple[User, User, PatientProfile]:
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )

    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )

    profile = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=admin,
        request_id=uuid4(),
        **_payload("patient@example.test"),
    )
    issued = people_services.issue_patient_invitation(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=profile.pk,
        expires_at=people_services.invitation_expiration_after(days=2),
        request_id=uuid4(),
    )
    patient_user = accept_invitation(
        raw_token=issued.raw_token,
        password="senha-sintetica-longa-e-nao-reutilizavel",
        first_name="Paciente",
        last_name="Exemplo",
    )
    profile.refresh_from_db()
    return therapist, patient_user, profile


def _force_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


# ---------------------------------------------------------------------------
# 8.7.4 Catalog & Assignment Tests
# ---------------------------------------------------------------------------


def test_seed_default_exercises() -> None:
    """8.7.4.4: Initial seed exercises for breathing and self-compassion."""
    clinic = ClinicFactory.create()
    therapist, _patient_user, _profile = _setup_clinic_therapist_and_patient(clinic)

    created = exercise_services.ensure_default_exercises_for_clinic(
        clinic_id=clinic.pk, author=therapist
    )
    assert len(created) == 4
    titles = [e.title for e in created]
    assert any("Respiração" in t for t in titles)
    assert any("autocompaixão" in t for t in titles)
    assert any("valores" in t for t in titles)
    assert any("problemas" in t for t in titles)

    # Calling again is idempotent
    second = exercise_services.ensure_default_exercises_for_clinic(
        clinic_id=clinic.pk, author=therapist
    )
    assert len(second) == 0


def test_create_and_version_exercise() -> None:
    """8.7.4.1 & 8.7.4.2: Create and version exercise template."""
    clinic = ClinicFactory.create()
    therapist, _patient_user, profile = _setup_clinic_therapist_and_patient(clinic)

    exercise = exercise_services.create_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        title="Exercício de Ancoragem",
        instructions="Sinta os pés no chão por 3 minutos.",
        status=ExerciseStatus.PUBLISHED,
        request_id=uuid4(),
    )
    assert exercise.version == 1

    # Assign it
    exercise_services.assign_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        exercise_id=exercise.pk,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
    )

    # Updating now creates version 2 because it's published and assigned
    v2 = exercise_services.update_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        exercise_id=exercise.pk,
        title="Exercício de Ancoragem Avançado",
        instructions="Sinta os pés no chão e observe a respiração.",
        status=ExerciseStatus.PUBLISHED,
        request_id=uuid4(),
    )
    assert v2.version == 2
    assert v2.parent_exercise == exercise


def test_non_therapist_cannot_manage_catalog() -> None:
    """8.7.4.1: Non-therapist cannot create exercise templates."""
    clinic = ClinicFactory.create()
    _therapist, patient_user, _profile = _setup_clinic_therapist_and_patient(clinic)

    with pytest.raises(PermissionDenied):
        exercise_services.create_exercise(
            clinic_id=clinic.pk,
            actor=patient_user,
            title="Não autorizado",
            instructions="Instruções",
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.7.5 Execution & Comments Tests
# ---------------------------------------------------------------------------


def test_exercise_execution_and_semaphore() -> None:
    """8.7.5.1 & 8.7.5.2: Draft save, resume, submit with visibility semaphore."""
    clinic = ClinicFactory.create()
    therapist, patient_user, profile = _setup_clinic_therapist_and_patient(clinic)

    exercise = exercise_services.create_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        title="Exercício de Atenção Plena",
        instructions="Observe os sons ao seu redor.",
        status=ExerciseStatus.PUBLISHED,
        request_id=uuid4(),
    )

    assignment = exercise_services.assign_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        exercise_id=exercise.pk,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
    )

    # Patient confirms assignment
    exercise_services.confirm_assignment(
        clinic_id=clinic.pk,
        actor=patient_user,
        assignment_id=assignment.pk,
        request_id=uuid4(),
    )

    # Patient starts execution session
    execution = exercise_services.start_or_resume_execution(
        clinic_id=clinic.pk,
        actor=patient_user,
        assignment_id=assignment.pk,
        request_id=uuid4(),
    )
    assert execution.is_draft is True

    # Patient saves draft
    exercise_services.save_execution_draft(
        clinic_id=clinic.pk,
        actor=patient_user,
        execution_id=execution.pk,
        step_number=1,
        response_data={"text": "Notei o som do vento."},
        request_id=uuid4(),
    )

    # Patient submits finished execution with Verde (SHAREABLE)
    submitted = exercise_services.submit_execution(
        clinic_id=clinic.pk,
        actor=patient_user,
        execution_id=execution.pk,
        response_data={"text": "Notei o som do vento e dos carros. Me acalmou."},
        visibility=ExerciseVisibility.SHAREABLE,
        request_id=uuid4(),
    )
    assert submitted.is_draft is False
    assert submitted.completed_at is not None

    # Therapist can comment because visibility is SHAREABLE (Verde)
    comment = exercise_services.comment_on_execution(
        clinic_id=clinic.pk,
        actor=therapist,
        execution_id=submitted.pk,
        content="Ótima observação! A ancoragem auditiva ajuda muito.",
        request_id=uuid4(),
    )
    assert comment.author == therapist


def test_private_visibility_blocks_therapist_comments() -> None:
    """8.7.5.3: Private (Vermelho) execution blocks therapist access and comments."""
    clinic = ClinicFactory.create()
    therapist, patient_user, profile = _setup_clinic_therapist_and_patient(clinic)

    exercise = exercise_services.create_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        title="Reflexão Pessoal",
        instructions="Escreva seus sentimentos.",
        status=ExerciseStatus.PUBLISHED,
        request_id=uuid4(),
    )

    assignment = exercise_services.assign_exercise(
        clinic_id=clinic.pk,
        actor=therapist,
        exercise_id=exercise.pk,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
    )

    execution = exercise_services.start_or_resume_execution(
        clinic_id=clinic.pk,
        actor=patient_user,
        assignment_id=assignment.pk,
        request_id=uuid4(),
    )

    submitted = exercise_services.submit_execution(
        clinic_id=clinic.pk,
        actor=patient_user,
        execution_id=execution.pk,
        response_data={"text": "Reflexão íntima..."},
        visibility=ExerciseVisibility.PRIVATE,
        request_id=uuid4(),
    )

    # Attempting to comment on private execution raises PermissionDenied
    with pytest.raises(PermissionDenied, match="privada pelo paciente"):
        exercise_services.comment_on_execution(
            clinic_id=clinic.pk,
            actor=therapist,
            execution_id=submitted.pk,
            content="Comentário não permitido",
            request_id=uuid4(),
        )


def test_exercise_http_flow(client: Client) -> None:
    """8.7.4 & 8.7.5: Full HTTP flow for catalog, assignment, execution and comments."""
    clinic = ClinicFactory.create()
    therapist, patient_user, profile = _setup_clinic_therapist_and_patient(clinic)

    # 1. Therapist creates exercise template
    _force_client(client, clinic, therapist)
    res = client.post(
        reverse("exercise_create"),
        data={
            "title": "Respiração Guiada",
            "instructions": "Inspire 4s, segure 4s, exale 4s.",
            "approach": "Mindfulness",
            "estimated_minutes": "5",
            "response_format": ResponseFormat.TEXT,
            "status": ExerciseStatus.PUBLISHED,
        },
    )
    assert res.status_code == 302

    exercise = TherapeuticExercise.objects.for_clinic(clinic.pk).get(
        title="Respiração Guiada"
    )

    # 2. Therapist assigns exercise to patient
    assign_res = client.post(
        reverse("exercise_assign", kwargs={"exercise_id": exercise.pk}),
        data={
            "patient_profile_id": str(profile.pk),
            "frequency": "Diária",
            "due_date": "",
            "notes": "Pratique antes de dormir.",
        },
    )
    assert assign_res.status_code == 302

    assignment = ExerciseAssignment.objects.for_clinic(clinic.pk).get(
        exercise_id=exercise.pk, patient_profile_id=profile.pk
    )

    # 3. Patient views exercises list and executes
    _force_client(client, clinic, patient_user)
    list_res = client.get(reverse("patient_exercise_list"))
    assert list_res.status_code == 200
    assert "Respiração Guiada" in list_res.content.decode()

    # Patient executes
    execute_res = client.post(
        reverse(
            "patient_exercise_execute",
            kwargs={"assignment_id": assignment.pk},
        ),
        data={
            "action": "submit",
            "response_text": "Me senti mais calmo.",
            "visibility": ExerciseVisibility.SHAREABLE,
        },
    )
    assert execute_res.status_code == 302

    execution = ExerciseExecution.objects.for_clinic(clinic.pk).get(
        assignment_id=assignment.pk
    )

    # 4. Therapist views execution response and adds comment
    _force_client(client, clinic, therapist)
    detail_res = client.get(
        reverse(
            "exercise_execution_detail",
            kwargs={"execution_id": execution.pk},
        )
    )
    assert detail_res.status_code == 200
    assert "Me senti mais calmo." in detail_res.content.decode()

    comment_res = client.post(
        reverse(
            "exercise_execution_detail",
            kwargs={"execution_id": execution.pk},
        ),
        data={"content": "Excelente progresso!"},
    )
    assert comment_res.status_code == 302

    assert (
        ExerciseComment.objects.for_clinic(clinic.pk)
        .filter(execution_id=execution.pk)
        .count()
        == 1
    )
