"""Tests for assistive clinical drafting and human-in-the-loop review (PRD 8.19.1)."""

from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from ai_assistant.contracts import AiReviewStatus, AiTaskType
from ai_assistant.models import AiAssistantRolloutFlag, AiModelInventory
from ai_assistant.services import (
    generate_clinical_draft,
    review_and_incorporate_draft,
)
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    clinic = ClinicFactory.create(name="Clínica IA Assistiva")
    AiAssistantRolloutFlag.objects.for_clinic(clinic.id).create(
        clinic=clinic, is_enabled=True, emergency_kill_switch=False
    )
    return clinic


@pytest.fixture
def therapist_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_ia@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(db: Any, clinic: Clinic, therapist_user: Any) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist_user,
        full_name="Paciente IA",
        birth_date="1992-06-15",
    )


@pytest.fixture
def approved_model(db: Any) -> AiModelInventory:
    return AiModelInventory.objects.create(
        name="ClinicalDraft-LLM",
        version="1.0",
        provider="InternalSecureHost",
        processing_region="sa-east-1",
        legal_basis="Legítimo Interesse",
        reevaluation_date="2027-01-01",
        is_active=True,
    )


def test_generate_clinical_draft_creates_transient_session(
    clinic: Clinic,
    therapist_user: Any,
    patient_profile: PatientProfile,
    approved_model: AiModelInventory,
) -> None:
    session = generate_clinical_draft(
        clinic_id=clinic.id,
        author_user=therapist_user,
        patient_id=patient_profile.id,
        model_inventory=approved_model,
        prompt_text="Paciente relata melhora no sono após higiene do sono.",
        source_snippets=["Observação em sessão sobre sono estável."],
        task_type=AiTaskType.CLINICAL_SYNTHESIS.value,
    )
    assert session.review_status == AiReviewStatus.DRAFT.value
    assert "[Fonte 1]" in session.generated_draft
    assert "requer conferência integral" in session.uncertainty_notes
    assert session.patient_id == patient_profile.id
    assert session.author_id == therapist_user.pk


def test_generate_draft_fails_when_tenant_ai_disabled(
    clinic: Clinic,
    therapist_user: Any,
    approved_model: AiModelInventory,
) -> None:
    flag = AiAssistantRolloutFlag.objects.for_clinic(clinic.id).first()
    assert flag is not None
    flag.is_enabled = False
    flag.save(update_fields=["is_enabled"])

    with pytest.raises(PermissionDenied):
        generate_clinical_draft(
            clinic_id=clinic.id,
            author_user=therapist_user,
            patient_id=uuid4(),
            model_inventory=approved_model,
            prompt_text="Resumo da sessão",
            source_snippets=[],
        )


def test_generate_draft_fails_when_kill_switch_active(
    clinic: Clinic,
    therapist_user: Any,
    approved_model: AiModelInventory,
) -> None:
    flag = AiAssistantRolloutFlag.objects.for_clinic(clinic.id).first()
    assert flag is not None
    flag.emergency_kill_switch = True
    flag.save(update_fields=["emergency_kill_switch"])

    with pytest.raises(PermissionDenied):
        generate_clinical_draft(
            clinic_id=clinic.id,
            author_user=therapist_user,
            patient_id=uuid4(),
            model_inventory=approved_model,
            prompt_text="Resumo da sessão",
            source_snippets=[],
        )


def test_generate_draft_exceeding_max_input_length_rejected(
    clinic: Clinic,
    therapist_user: Any,
    approved_model: AiModelInventory,
) -> None:
    huge_prompt = "A" * 4001
    with pytest.raises(ValueError, match="Input text exceeds maximum"):
        generate_clinical_draft(
            clinic_id=clinic.id,
            author_user=therapist_user,
            patient_id=uuid4(),
            model_inventory=approved_model,
            prompt_text=huge_prompt,
            source_snippets=[],
        )


def test_review_and_reject_draft(
    clinic: Clinic,
    therapist_user: Any,
    patient_profile: PatientProfile,
    approved_model: AiModelInventory,
) -> None:
    session = generate_clinical_draft(
        clinic_id=clinic.id,
        author_user=therapist_user,
        patient_id=patient_profile.id,
        model_inventory=approved_model,
        prompt_text="Paciente relatou ansiedade leve.",
        source_snippets=["Relato de ansiedade em situação social."],
    )
    reviewed = review_and_incorporate_draft(
        clinic_id=clinic.id,
        session_id=session.id,
        reviewer_user=therapist_user,
        action=AiReviewStatus.REJECTED.value,
    )
    assert reviewed.review_status == AiReviewStatus.REJECTED.value
    assert reviewed.reviewed_by_id == therapist_user.pk
    assert reviewed.reviewed_at is not None


def test_review_and_accept_draft_requires_nominal_confirmation(
    clinic: Clinic,
    therapist_user: Any,
    patient_profile: PatientProfile,
    approved_model: AiModelInventory,
) -> None:
    session = generate_clinical_draft(
        clinic_id=clinic.id,
        author_user=therapist_user,
        patient_id=patient_profile.id,
        model_inventory=approved_model,
        prompt_text="Paciente manteve rotina de caminhadas.",
        source_snippets=["Caminhadas diárias realizadas."],
    )
    # Missing responsibility acknowledgement raises ValueError
    with pytest.raises(ValueError, match="Nominal confirmation name"):
        review_and_incorporate_draft(
            clinic_id=clinic.id,
            session_id=session.id,
            reviewer_user=therapist_user,
            action=AiReviewStatus.ACCEPTED.value,
            nominal_confirmation_name="",
            responsibility_acknowledged=False,
        )

    # Valid nominal confirmation and responsibility succeeds
    reviewed = review_and_incorporate_draft(
        clinic_id=clinic.id,
        session_id=session.id,
        reviewer_user=therapist_user,
        action=AiReviewStatus.ACCEPTED.value,
        nominal_confirmation_name="Dr. João Terapeuta",
        purpose_note="Acompanhamento evolutivo semanal",
        responsibility_acknowledged=True,
    )
    assert reviewed.review_status == AiReviewStatus.ACCEPTED.value
    assert reviewed.edited_content == session.generated_draft


def test_review_with_professional_edits(
    clinic: Clinic,
    therapist_user: Any,
    patient_profile: PatientProfile,
    approved_model: AiModelInventory,
) -> None:
    session = generate_clinical_draft(
        clinic_id=clinic.id,
        author_user=therapist_user,
        patient_id=patient_profile.id,
        model_inventory=approved_model,
        prompt_text="Texto bruto com termos informais.",
        source_snippets=["Sessão 3."],
    )
    edited_text = "Texto clínico corrigido e validado pelo profissional."
    reviewed = review_and_incorporate_draft(
        clinic_id=clinic.id,
        session_id=session.id,
        reviewer_user=therapist_user,
        action=AiReviewStatus.EDITED.value,
        edited_content=edited_text,
        nominal_confirmation_name="Dra. Maria Terapeuta",
        purpose_note="Registro de evolução após revisão humana",
        responsibility_acknowledged=True,
    )
    assert reviewed.review_status == AiReviewStatus.EDITED.value
    assert reviewed.edited_content == edited_text

