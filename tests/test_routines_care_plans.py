"""Tests for care plans, professional signing, and patient autonomy (8.14.5)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from routines import care_plan_services, selectors
from routines.models import (
    CarePlanStatus,
    PatientResponseChoice,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Planos de Cuidado Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.plano@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(test_clinic: Clinic):
    user = UserFactory.create(email="terapeuta.plano@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def other_patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="outro.paciente@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(test_clinic: Clinic, patient_user) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Plano de Cuidado",
        birth_date=date(1991, 7, 2),
    )


@pytest.mark.django_db
def test_propose_care_plan_draft_and_actions(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user,
    other_patient_user,
) -> None:
    """Clinicians propose draft care plans with actions, blocked for non-clinicians."""
    # Unauthorized proposal by patient
    with pytest.raises(ValidationError, match="Apenas profissionais de saúde"):
        care_plan_services.propose_care_plan(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            professional_user=other_patient_user,
            title="Plano não autorizado",
            objective="Automedicação",
            clinical_rationale="Nenhuma",
        )

    # Authorized proposal by therapist
    plan = care_plan_services.propose_care_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        professional_user=therapist_user,
        title="Plano de Manejo da Ansiedade e Rotina do Sono",
        objective="Restabelecer regularidade circadiana e reduzir ruminação",
        clinical_rationale="Higiene do sono associada a técnicas de relaxamento",
        contraindications="Evitar cafeína após as 14h",
        actions_data=[
            {
                "description": "Desconexão de telas 30 min antes de deitar",
                "frequency": "daily",
                "guidance": "Substituir telas por luz quente e leitura leve",
                "is_mandatory": False,
            },
            {
                "description": "Prática de respiração diafragmática",
                "frequency": "daily",
                "guidance": "5 minutos ao deitar",
                "is_mandatory": False,
            },
        ],
    )
    assert plan.status == CarePlanStatus.DRAFT
    assert plan.actions.count() == 2


@pytest.mark.django_db
def test_sign_care_plan_activates_with_cryptographic_digest(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user,
) -> None:
    """Care plans require professional signature and digest before becoming active."""
    plan = care_plan_services.propose_care_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        professional_user=therapist_user,
        title="Plano de Retomada de Atividades",
        objective="Ativação comportamental gradual",
        clinical_rationale="TCC para episódio depressivo leve",
    )
    assert plan.status == CarePlanStatus.DRAFT
    assert plan.signature_digest == ""

    # Sign plan
    signed = care_plan_services.sign_care_plan(
        clinic_id=test_clinic.id,
        care_plan_id=plan.id,
        signing_professional=therapist_user,
    )
    assert signed.status == CarePlanStatus.ACTIVE
    assert signed.signed_at is not None
    assert len(signed.signature_digest) == 64

    # Audit log recorded
    audit = (
        AuditEvent.infrastructure_objects.filter(clinic_id=test_clinic.id)
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.action == "routines.care_plan_signed"


@pytest.mark.django_db
def test_patient_autonomous_response_workflow(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    patient_user,
    therapist_user,
) -> None:
    """Patients can accept, pause, or request review of care plans autonomously."""
    plan = care_plan_services.propose_care_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        professional_user=therapist_user,
        title="Plano Autônomo",
        objective="Apoio rotina",
        clinical_rationale="Clínica geral",
    )
    care_plan_services.sign_care_plan(
        clinic_id=test_clinic.id,
        care_plan_id=plan.id,
        signing_professional=therapist_user,
    )

    # Patient accepts plan
    resp_accept = care_plan_services.respond_to_care_plan(
        clinic_id=test_clinic.id,
        care_plan_id=plan.id,
        decision=PatientResponseChoice.ACCEPTED,
        patient_notes="De acordo com as metas",
        actor_id=patient_user.id,
    )
    assert resp_accept.decision == PatientResponseChoice.ACCEPTED
    assert resp_accept.plan_version_reviewed == 1

    # Later, patient pauses plan
    resp_pause = care_plan_services.respond_to_care_plan(
        clinic_id=test_clinic.id,
        care_plan_id=plan.id,
        decision=PatientResponseChoice.PAUSED,
        patient_notes="Semana de viagens a trabalho",
        actor_id=patient_user.id,
    )
    plan.refresh_from_db()
    assert resp_pause.decision == PatientResponseChoice.PAUSED
    assert plan.status == CarePlanStatus.PAUSED

    # Audit logged
    audits = AuditEvent.infrastructure_objects.filter(
        clinic_id=test_clinic.id,
        action="routines.care_plan_patient_response",
    )
    assert audits.count() == 2


@pytest.mark.django_db
def test_professional_supervision_dashboard_overview(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user,
) -> None:
    """Supervision dashboard aggregates habits, sleep, and care plans transparently."""
    plan = care_plan_services.propose_care_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        professional_user=therapist_user,
        title="Plano Ativo Supervisionado",
        objective="Acompanhamento",
        clinical_rationale="Clínico",
    )
    care_plan_services.sign_care_plan(
        clinic_id=test_clinic.id,
        care_plan_id=plan.id,
        signing_professional=therapist_user,
    )

    dashboard = selectors.professional_supervision_dashboard(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        period_days=14,
    )
    assert dashboard["patient_profile_id"] == str(patient_profile.id)
    assert dashboard["period_days"] == 14
    assert dashboard["active_care_plans_count"] == 1
    assert "habits" in dashboard
    assert "sleep" in dashboard
