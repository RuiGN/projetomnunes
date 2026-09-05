"""Tests for relapse plans, granular section sharing, and post-lapse (8.15.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from wellness import relapse_services
from wellness.models import (
    RelapsePlanSectionType,
)
from wellness.policies import can_access_relapse_plan


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Prevenção de Recaída Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.recaida@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="terapeuta.recaida@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def other_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="desconhecido.recaida@test.org")
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
        full_name="Paciente Prevenção Recaída",
        birth_date=date(1992, 3, 29),
    )


@pytest.mark.django_db
def test_create_and_version_relapse_prevention_plan(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Relapse plan contains structured sections and increments version on updates."""
    sections = [
        {
            "section_type": RelapsePlanSectionType.TRIGGERS,
            "title": "Gatilhos Conhecidos",
            "content": "Ambientes com álcool disponível; noites mal dormidas.",
            "order": 1,
        },
        {
            "section_type": RelapsePlanSectionType.EARLY_WARNING_SIGNS,
            "title": "Sinais Precoces",
            "content": "Isolamento social, irritabilidade e pensamentos de lapso.",
            "order": 2,
        },
        {
            "section_type": RelapsePlanSectionType.COPING_STRATEGIES,
            "title": "Estratégias de Enfrentamento",
            "content": "Praticar técnica 5-4-3-2-1, ligar para irmão ou sair do local.",
            "order": 3,
        },
    ]

    plan = relapse_services.create_or_update_relapse_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Meu Plano Pessoal de Proteção",
        sections_data=sections,
        disclaimer_acknowledged=True,
        actor_id=patient_user.id,
    )
    assert plan.version == 1
    assert plan.disclaimer_acknowledged is True
    assert plan.sections.count() == 3

    # Update increments version
    updated_plan = relapse_services.create_or_update_relapse_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Meu Plano Pessoal de Proteção (Revisado)",
        sections_data=[
            {
                "section_type": RelapsePlanSectionType.PROTECTIVE_FACTORS,
                "title": "Fatores Protetores",
                "content": "Rotina matinal de caminhada e apoio da família.",
                "order": 4,
            }
        ],
        actor_id=patient_user.id,
    )
    assert updated_plan.version == 2
    assert updated_plan.sections.count() == 4


@pytest.mark.django_db
def test_granular_section_sharing_and_revocation(
    test_clinic: Clinic,
    patient_profile: PatientProfile,
    therapist_user: User,
    other_user: User,
) -> None:
    """Sharing allows granular section access with expiration and instant revocation."""
    plan = relapse_services.create_or_update_relapse_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Plano para Compartilhar",
    )

    # Share triggers and coping strategies with therapist for 14 days
    valid_until = datetime.now(UTC) + timedelta(days=14)
    share = relapse_services.share_relapse_plan_section(
        clinic_id=test_clinic.id,
        plan_id=plan.id,
        recipient_label="Dra. Paula / Terapeuta",
        recipient_user=therapist_user,
        section_type=RelapsePlanSectionType.COPING_STRATEGIES,
        valid_until=valid_until,
    )
    assert share.is_revoked is False

    # Therapist has access
    assert (
        can_access_relapse_plan(
            user=therapist_user,
            clinic_id=test_clinic.id,
            relapse_plan_id=plan.id,
            patient_profile_id=patient_profile.id,
        )
        is True
    )

    # Unknown user has no access
    assert (
        can_access_relapse_plan(
            user=other_user,
            clinic_id=test_clinic.id,
            relapse_plan_id=plan.id,
            patient_profile_id=patient_profile.id,
        )
        is False
    )

    # Patient revokes share immediately
    revoked = relapse_services.revoke_relapse_plan_share(
        clinic_id=test_clinic.id,
        share_id=share.id,
    )
    assert revoked.is_revoked is True

    # Therapist access is now revoked
    assert (
        can_access_relapse_plan(
            user=therapist_user,
            clinic_id=test_clinic.id,
            relapse_plan_id=plan.id,
            patient_profile_id=patient_profile.id,
        )
        is False
    )


@pytest.mark.django_db
def test_post_lapse_supportive_event_registration(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Post-lapse flow is supportive, non-punitive, and logs protective actions."""
    plan = relapse_services.create_or_update_relapse_plan(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )

    # Context required
    with pytest.raises(ValidationError, match="Contexto ou gatilho"):
        relapse_services.record_post_lapse_event(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            context_and_triggers="",
        )

    # Valid post-lapse log
    record = relapse_services.record_post_lapse_event(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        relapse_plan_id=plan.id,
        context_and_triggers="Evento social imprevisto e estresse financeiro",
        protective_actions_taken="Saí do local imediatamente e acionei apoio",
        support_requested=True,
        notes="Desejo revisar estratégias de ambientes seguros na próxima consulta",
        actor_id=patient_user.id,
    )
    assert record.support_requested is True
    assert record.relapse_plan_id == plan.id

    # Audit event logged
    audit = (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=test_clinic.id,
            action="wellness.post_lapse_event_logged",
        )
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.resource_id == str(record.id)
