"""Acceptance tests for PRD 8.7.3 low-energy mode."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import accept_invitation
from clinics.models import Clinic, ClinicMembership
from goals import low_energy_services as le_services
from goals.low_energy_models import LowEnergyActionTemplate, LowEnergyMode
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


def _linked_patient(
    clinic: Clinic, *, email: str = "um@example.test"
) -> tuple[User, User, PatientProfile]:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    profile = people_services.register_patient_profile(
        clinic_id=clinic.pk, actor=administrator, request_id=uuid4(), **_payload(email)
    )
    issued = people_services.issue_patient_invitation(
        clinic_id=clinic.pk,
        actor=administrator,
        patient_profile_id=profile.pk,
        expires_at=people_services.invitation_expiration_after(days=2),
        request_id=uuid4(),
    )
    user = accept_invitation(
        raw_token=issued.raw_token,
        password="senha-sintetica-longa-e-nao-reutilizavel",
        first_name="Paciente",
        last_name="Exemplo",
    )
    profile.refresh_from_db()
    return administrator, user, profile


def _configure(clinic: Clinic, user: User) -> LowEnergyActionTemplate:
    return le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber um copo de água",
        action_2="Abrir a janela",
        action_3="Realizar uma etapa curta de uma meta",
        request_id=uuid4(),
    )


def _force_patient_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


# ---------------------------------------------------------------------------
# 8.7.3.1 Configuration tests
# ---------------------------------------------------------------------------


def test_configure_actions_with_authorship() -> None:
    """8.7.3.1: Minimal actions configured with authorship and versioning."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)

    template = le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber água",
        action_2="Abrir a janela",
        action_3="Uma etapa curta",
        request_id=uuid4(),
    )
    assert template.version == 1
    assert template.is_active is True
    assert template.author == user
    assert template.action_1 == "Beber água"

    # New configuration supersedes the previous version
    second = le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Nova ação",
        request_id=uuid4(),
    )
    assert second.version == 2
    template.refresh_from_db()
    assert template.is_active is False
    active_count = LowEnergyActionTemplate.infrastructure_objects.filter(
        clinic_id=clinic.pk, patient_profile=template.patient_profile, is_active=True
    ).count()
    assert active_count == 1


def test_configure_requires_at_least_one_action() -> None:
    """8.7.3.1: Empty configuration is rejected."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)

    with pytest.raises(ValidationError, match="pelo menos uma ação"):
        le_services.configure_low_energy_actions(
            clinic_id=clinic.pk,
            actor=user,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.7.3.2 One-touch activation tests
# ---------------------------------------------------------------------------


def test_activate_uses_configured_actions_with_limit() -> None:
    """8.7.3.2: Activation uses configured actions; max 3 shown; capped duration."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)
    le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber água",
        action_2="Abrir a janela",
        action_3="Uma etapa curta",
        request_id=uuid4(),
    )

    session = le_services.activate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        duration_hours=99,
        request_id=uuid4(),
    )
    actions = [session.action_1, session.action_2, session.action_3]
    assert sum(1 for a in actions if a) == 3
    # Duration capped at 24h
    assert session.ends_at - session.started_at <= timedelta(hours=24)
    assert session.is_active is True
    assert session.ended_at is None

    # Idempotent one-touch: second activation returns the same session
    again = le_services.activate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        request_id=uuid4(),
    )
    assert again.pk == session.pk


def test_activation_requires_configured_template() -> None:
    """8.7.3.2: Activation without configured actions is rejected."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)

    with pytest.raises(ValidationError, match="Configure suas ações"):
        le_services.activate_low_energy_mode(
            clinic_id=clinic.pk,
            actor=user,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.7.3.3 Notification suppression tests
# ---------------------------------------------------------------------------


def test_non_essential_notifications_suppressed_essential_pass() -> None:
    """8.7.3.3: Essential notifications continue; non-essential are suppressed."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber água",
        request_id=uuid4(),
    )
    session = le_services.activate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        request_id=uuid4(),
    )

    assert (
        le_services.notifications_allowed(
            clinic_id=clinic.pk,
            patient_profile_id=profile.pk,
            essential=True,
        )
        is True
    )
    assert (
        le_services.notifications_allowed(
            clinic_id=clinic.pk,
            patient_profile_id=profile.pk,
            essential=False,
        )
        is False
    )

    # After manual end, non-essential notifications flow again
    le_services.deactivate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        request_id=uuid4(),
    )
    session.refresh_from_db()
    assert session.end_reason == "manual"
    assert (
        le_services.notifications_allowed(
            clinic_id=clinic.pk,
            patient_profile_id=profile.pk,
            essential=False,
        )
        is True
    )


# ---------------------------------------------------------------------------
# 8.7.3.4 Manual end, auto-expiry and absence of clinical escalation
# ---------------------------------------------------------------------------


def test_auto_expiration_of_stale_sessions() -> None:
    """8.7.3.4: Sessions past their end are expired automatically."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)
    le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber água",
        request_id=uuid4(),
    )
    session = le_services.activate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        duration_hours=1,
        request_id=uuid4(),
    )

    # Simulate the end of the window in the past
    LowEnergyMode.infrastructure_objects.filter(pk=session.pk).update(
        ends_at=timezone.now() - timedelta(minutes=1)
    )

    expired = le_services.expire_stale_low_energy_sessions()
    assert expired == 1
    session.refresh_from_db()
    assert session.end_reason == "expired"
    assert session.ended_at is not None


def test_low_energy_never_diagnoses_or_escalates() -> None:
    """8.7.3.4: The mode creates no diagnosis, score or clinical escalation."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)
    le_services.configure_low_energy_actions(
        clinic_id=clinic.pk,
        actor=user,
        action_1="Beber água",
        request_id=uuid4(),
    )
    session = le_services.activate_low_energy_mode(
        clinic_id=clinic.pk,
        actor=user,
        request_id=uuid4(),
    )

    # The model carries only preferences, never clinical state
    assert not hasattr(session, "diagnosis")
    assert not hasattr(session, "risk_score")
    assert not hasattr(session, "escalation_level")
    assert session.suppress_non_essential_notifications is True


def test_low_energy_http_flow(client: Client) -> None:
    """8.7.3.2: HTTP configure, activate, and deactivate flow."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    # Configure actions
    config_res = client.post(
        reverse("low_energy_configure"),
        data={
            "action_1": "Beber um copo de água",
            "action_2": "Abrir a janela",
            "action_3": "Uma etapa curta",
        },
    )
    assert config_res.status_code == 302

    # Activate with one touch
    activate_res = client.post(
        reverse("low_energy_activate"), data={"duration_hours": "8"}
    )
    assert activate_res.status_code == 302

    session = LowEnergyMode.infrastructure_objects.get(
        clinic_id=clinic.pk, patient_profile__user_id=user.pk
    )
    assert session.is_active is True

    # Simplified screen shows the actions and end option
    home_res = client.get(reverse("low_energy_home"))
    assert home_res.status_code == 200
    content = home_res.content.decode()
    assert "Modo baixa energia" in content
    assert "Beber um copo de água" in content
    assert "não substitui orientação de crise" in content

    # Manual end
    deactivate_res = client.post(reverse("low_energy_deactivate"))
    assert deactivate_res.status_code == 302
    session.refresh_from_db()
    assert session.ended_at is not None
    assert session.end_reason == "manual"
