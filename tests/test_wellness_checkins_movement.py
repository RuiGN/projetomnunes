"""Tests for wellness check-ins, movement plans, and discomfort feedback (8.15.2)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from wellness import selectors, services
from wellness.models import (
    MovementPlanStatus,
)


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Movimento Seguro Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.movimento@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(test_clinic: Clinic):
    user = UserFactory.create(email="terapeuta.movimento@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def other_patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="outro.paciente.mov@test.org")
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
        full_name="Paciente Movimento e Check-ins",
        birth_date=date(1989, 11, 23),
    )


@pytest.mark.django_db
def test_wellness_checkin_scales_and_privacy_preference(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user
) -> None:
    """Check-ins enforce 1-5 scales and respect private vs shared preference."""
    day = date(2026, 9, 3)

    # Invalid energy scale
    with pytest.raises(ValidationError, match="Nível de energia.*1 a 5"):
        services.record_wellness_checkin(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            checkin_date=day,
            energy_level=6,
        )

    # Valid check-in, private by default
    checkin = services.record_wellness_checkin(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        checkin_date=day,
        energy_level=4,
        perceived_mood=3,
        stress_level=2,
        readiness_disposition=4,
        context_notes="Dia calmo após boa noite de sono",
        is_shared_with_clinic=False,
    )
    assert checkin.is_shared_with_clinic is False

    # Summary query only_shared=True returns 0 shared check-ins
    summary_shared = selectors.wellness_checkins_summary(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=day,
        end_date=day,
        only_shared=True,
    )
    assert summary_shared["total_checkins"] == 0

    # Summary for patient returns the record
    summary_patient = selectors.wellness_checkins_summary(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=day,
        end_date=day,
        only_shared=False,
    )
    assert summary_patient["total_checkins"] == 1
    assert summary_patient["avg_energy"] == 4.0


@pytest.mark.django_db
def test_safe_movement_plan_requires_professional_approval(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user,
    other_patient_user,
) -> None:
    """Movement plans require professional approval before activation."""
    # Proposal rejected if not healthcare professional
    with pytest.raises(ValidationError, match="Apenas profissionais habilitados"):
        services.propose_safe_movement_plan(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            prescribing_professional=other_patient_user,
            title="Plano não autorizado",
            objective="Autonomia",
            target_frequency="3x/semana",
            target_intensity="moderada",
            progression_guidelines="Nenhuma",
            stop_signals="Nenhum",
        )

    # Valid proposal by therapist
    plan = services.propose_safe_movement_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        prescribing_professional=therapist_user,
        title="Plano de Caminhada Progressiva e Alongamento",
        objective="Reativação motora gradual e redução da ansiedade somática",
        target_frequency="3 vezes por semana",
        target_intensity="Leve a moderada (RPE 3 a 5)",
        progression_guidelines="Aumentar 5 minutos por semana se tolerado",
        stop_signals="Dor no peito, tontura, falta de ar severa ou palpitações",
        adaptations="Realizar pausas para hidratação a cada 10 minutos",
    )
    assert plan.status == MovementPlanStatus.DRAFT
    assert plan.signature_digest == ""

    # Sign plan by therapist activates it
    signed_plan = services.approve_safe_movement_plan(
        clinic_id=test_clinic.id,
        plan_id=plan.id,
        signing_professional=therapist_user,
    )
    assert signed_plan.status == MovementPlanStatus.ACTIVE
    assert signed_plan.signature_digest != ""
    assert signed_plan.signed_at is not None


@pytest.mark.django_db
def test_movement_plan_discomfort_feedback_pauses_plan(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user,
    patient_user,
) -> None:
    """Discomfort or pain feedback immediately pauses the active plan for review."""
    plan = services.propose_safe_movement_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        prescribing_professional=therapist_user,
        title="Plano de Fortalecimento",
        objective="Fortalecimento postural",
        target_frequency="Diária",
        target_intensity="Moderada",
        progression_guidelines="Manter estabilidade",
        stop_signals="Dor articular ou tontura",
    )
    services.approve_safe_movement_plan(
        clinic_id=test_clinic.id,
        plan_id=plan.id,
        signing_professional=therapist_user,
    )
    assert plan.status == MovementPlanStatus.DRAFT  # from original variable
    plan.refresh_from_db()
    assert plan.status == MovementPlanStatus.ACTIVE

    # Patient reports discomfort/pain
    feedback = services.record_plan_discomfort_feedback(
        clinic_id=test_clinic.id,
        plan_id=plan.id,
        patient_profile_id=patient_profile.id,
        feedback_type="dor",
        description="Dor aguda no joelho direito durante o terceiro exercício",
        actor_id=patient_user.id,
    )
    assert feedback.pause_plan_requested is True
    assert feedback.requires_professional_review is True

    # Plan is now PAUSED
    plan.refresh_from_db()
    assert plan.status == MovementPlanStatus.PAUSED

    # Audit event logged
    audit = (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=test_clinic.id,
            action="wellness.movement_plan_discomfort_paused",
        )
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.resource_id == str(feedback.id)
