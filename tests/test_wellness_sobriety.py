"""Tests for sobriety journey, craving check-ins, milestones, and contacts (8.15.3)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from wellness import selectors, sobriety_services
from wellness.models import (
    SobrietyGoalType,
)


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Sobriedade Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.sobriedade@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(test_clinic: Clinic, patient_user: User) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Jornada Sobriedade",
        birth_date=date(1987, 6, 14),
    )


@pytest.mark.django_db
def test_setup_sobriety_goal_and_non_punitive_restart(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Sobriety goals support private tracking and non-punitive redefinition."""
    ref_date = date(2026, 8, 1)

    # Blank substance/behavior error
    with pytest.raises(ValidationError, match="Especifique o foco ou objetivo"):
        sobriety_services.setup_sobriety_goal(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            substance_or_behavior="",
            reference_date=ref_date,
        )

    # Valid goal
    goal = sobriety_services.setup_sobriety_goal(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        goal_type=SobrietyGoalType.ABSTINENCE,
        substance_or_behavior="Álcool",
        reference_date=ref_date,
        motivations="Melhora na qualidade de vida e sono regular",
        hide_counter=False,
        is_private=True,
        actor_id=patient_user.id,
    )
    assert goal.initial_start_date == ref_date
    assert goal.restart_count == 0
    assert goal.is_private is True

    # Adjusting / restarting goal increments restart_count neutrally
    new_date = date(2026, 9, 1)
    adjusted = sobriety_services.adjust_or_restart_sobriety_goal(
        clinic_id=test_clinic.id,
        goal_id=goal.id,
        new_reference_date=new_date,
        new_motivations="Foco em um dia de cada vez após semana difícil",
        hide_counter=True,
        actor_id=patient_user.id,
    )
    assert adjusted.initial_start_date == ref_date  # Preserved
    assert adjusted.reference_date == new_date
    assert adjusted.restart_count == 1
    assert adjusted.hide_counter is True


@pytest.mark.django_db
def test_craving_checkin_with_optional_fields_and_privacy(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Craving self-report has optional fields and lock screen protection."""
    goal = sobriety_services.setup_sobriety_goal(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        substance_or_behavior="Tabaco",
        reference_date=date(2026, 9, 1),
    )

    # Invalid intensity
    with pytest.raises(ValidationError, match="Intensidade.*entre 1 e 10"):
        sobriety_services.record_craving_checkin(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            intensity=15,
        )

    # Valid report
    checkin = sobriety_services.record_craving_checkin(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        sobriety_goal_id=goal.id,
        intensity=7,
        triggers_context="Pausa do almoço em ambiente com fumantes",
        coping_strategy_used="Beber água gelada e caminhada de 5 minutos",
        perceived_outcome="Vontade diminuiu significativamente",
        protected_from_lockscreen=True,
    )
    assert checkin.intensity == 7
    assert checkin.protected_from_lockscreen is True


@pytest.mark.django_db
def test_private_milestones_and_support_contacts(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Milestones are private without ranking, and contacts require consent."""
    goal = sobriety_services.setup_sobriety_goal(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        substance_or_behavior="Álcool",
        reference_date=date(2026, 8, 1),
    )

    # Milestone
    milestone = sobriety_services.record_sobriety_milestone(
        clinic_id=test_clinic.id,
        sobriety_goal_id=goal.id,
        days_count=30,
        recognition_title="30 dias de foco e presença",
        is_private=True,
    )
    assert milestone.days_count == 30
    assert milestone.is_private is True

    # Support contact
    contact = sobriety_services.register_support_contact(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        name="Carlos Silva (Irmão)",
        relationship="Familiar",
        phone_number="+5511988887777",
        priority_order=1,
        consent_to_reach_out=True,
        availability_notes="Disponível preferencialmente à noite",
    )
    assert contact.priority_order == 1
    assert contact.consent_to_reach_out is True

    dashboard = selectors.sobriety_dashboard(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )
    assert len(dashboard["active_goals"]) == 1
    assert len(dashboard["support_contacts"]) == 1
    assert dashboard["support_contacts"][0]["name"] == "Carlos Silva (Irmão)"
