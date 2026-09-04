"""Tests for crisis mode, emergency numbers, grounding, and boundaries (8.15.5)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from wellness import crisis_services, selectors
from wellness.models import (
    MANDATORY_CRISIS_DISCLAIMER,
    CrisisResourceConfig,
    GroundingExercise,
)


@pytest.fixture
def test_clinic() -> Clinic:
    clinic = ClinicFactory.create(name="Clínica Modo Crise Teste")
    CrisisResourceConfig.infrastructure_objects.create(
        clinic=clinic,
        country_code="BR",
        emergency_medical_number="192",
        emergency_fire_number="193",
        emotional_support_number="188",
        custom_helpline_name="Caps 24h Regional",
        custom_helpline_number="+551130000000",
    )
    return clinic


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.crise@test.org")
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
        full_name="Paciente Modo Crise",
        birth_date=date(1994, 1, 10),
    )


@pytest.fixture
def grounding_exercises(test_clinic: Clinic) -> list[GroundingExercise]:
    ex1 = GroundingExercise.infrastructure_objects.create(
        clinic=test_clinic,
        title="Técnica de Aterramento 5-4-3-2-1",
        technique_type="sensory_grounding",
        instructions_markdown="Perceba 5 coisas que você vê, 4 que pode tocar...",
        steps=[
            "Observe 5 coisas que você pode ver ao seu redor",
            "Sinta 4 coisas que você pode tocar agora",
            "Ouça 3 sons ao seu redor",
            "Identifique 2 aromas ou cheiros",
            "Note 1 sabor na sua boca",
        ],
        duration_seconds=180,
        is_available_offline=True,
        can_exit_anytime=True,
    )
    ex2 = GroundingExercise.infrastructure_objects.create(
        clinic=test_clinic,
        title="Respiração em Caixa (4-4-4-4)",
        technique_type="box_breathing",
        instructions_markdown="Inspire em 4s, segure por 4s, expire em 4s.",
        steps=[
            "Inspire lentamente contando até 4",
            "Segure o ar contando até 4",
            "Solte o ar devagar contando até 4",
            "Aguarde com o pulmão vazio contando até 4",
        ],
        duration_seconds=120,
        is_available_offline=True,
        can_exit_anytime=True,
    )
    return [ex1, ex2]


@pytest.mark.django_db
def test_crisis_mode_displays_mandatory_disclaimer_and_numbers(
    test_clinic: Clinic,
    grounding_exercises: list[GroundingExercise],
) -> None:
    """Crisis payload prominently displays non-emergency notice and local numbers."""
    payload = selectors.crisis_resources_and_grounding(clinic_id=test_clinic.id)

    # Mandatory disclaimer must be present exactly
    assert (
        "Este aplicativo não é um serviço de emergência"
        in payload["mandatory_disclaimer"]
    )
    assert "não oferece monitoramento em tempo real" in payload["mandatory_disclaimer"]
    assert (
        "Em perigo imediato, acione agora o serviço de emergência"
        in payload["mandatory_disclaimer"]
    )

    # Emergency phone numbers
    assert payload["emergency_medical"] == "192"  # SAMU
    assert payload["emergency_fire"] == "193"  # Bombeiros
    assert payload["emotional_support"] == "188"  # CVV
    assert payload["custom_helpline"]["name"] == "Caps 24h Regional"

    # Offline grounding exercises loaded
    assert len(payload["grounding_exercises"]) == 2
    assert all(ex["can_exit_anytime"] is True for ex in payload["grounding_exercises"])


@pytest.mark.django_db
def test_emergency_touch_action_requires_explicit_confirmation(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user
) -> None:
    """Emergency touch actions strictly block initiation without user confirmation."""
    # Attempt without confirmation fails
    with pytest.raises(ValidationError, match="Confirmação explícita.*obrigatória"):
        crisis_services.trigger_emergency_touch_action(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            action_invoked="call_samu_192",
            confirmation_confirmed=False,
            actor_id=patient_user.id,
        )

    # Confirmed touch action succeeds and audits
    log = crisis_services.trigger_emergency_touch_action(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        action_invoked="call_samu_192",
        confirmation_confirmed=True,
        actor_id=patient_user.id,
    )
    assert log.confirmation_granted is True
    assert log.action_invoked == "call_samu_192"

    audit = (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=test_clinic.id,
            action="wellness.emergency_action_confirmed",
        )
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.resource_id == str(log.id)


@pytest.mark.django_db
def test_crisis_mode_offline_access_and_zero_clinical_promises(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user
) -> None:
    """Crisis mode operates offline and makes no clinical diagnostic promises."""
    # Patient accesses crisis mode under network disconnection
    log = crisis_services.log_crisis_mode_access(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        action_invoked="viewed_disclaimer",
        offline_mode_active=True,
        actor_id=patient_user.id,
    )
    assert log.offline_mode_active is True

    # Check that selector does not infer diagnoses from crisis logs
    payload = selectors.crisis_resources_and_grounding(clinic_id=test_clinic.id)
    assert "diagnóstico" not in payload
    assert "prescrição" not in payload
    assert "promessa_atendimento" not in payload
    # Mandatory disclaimer remains immutable
    assert payload["mandatory_disclaimer"] == MANDATORY_CRISIS_DISCLAIMER
