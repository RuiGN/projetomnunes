"""Acceptance tests for PRD 8.5.4 onboarding (clinic checklist + patient flow)."""

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
from onboarding import selectors as onboarding_selectors
from onboarding import services as onboarding_services
from onboarding.models import PatientOnboarding
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


def _patient_payload() -> PatientPayload:
    return {
        "full_name": "Marina Exemplo",
        "social_name": "Mari",
        "birth_date": date(1994, 5, 18),
        "gender": "woman",
        "email": "marina@example.test",
        "phone": "+55 11 99999-1234",
        "language_code": "pt-BR",
        "timezone_name": "America/Sao_Paulo",
        "accessibility_preferences": "",
        "address": {},
        "address_purpose": "",
        "emergency_contact": {},
        "emergency_contact_purpose": "",
    }


def _linked_patient(
    clinic: Clinic,
    *,
    email: str = "marina@example.test",
    phone: str = "+55 11 99999-1234",
) -> tuple[User, PatientProfile]:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    payload = _patient_payload()
    payload["email"] = email
    payload["phone"] = phone
    profile = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **payload,
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
        first_name="Marina",
        last_name="Exemplo",
    )
    profile.refresh_from_db()
    return user, profile


def test_clinic_checklist_reports_factual_items() -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )

    items = onboarding_selectors.clinic_onboarding_checklist(
        clinic_id=clinic.pk, actor=administrator
    )

    keys = [item.key for item in items]
    assert keys == [
        "clinic_profile",
        "professionals_invited",
        "terms_published",
        "permissions_configured",
        "first_patient",
    ]
    # Administrador recém-criado ainda não configurou a clínica.
    by_key = {item.key: item for item in items}
    assert by_key["clinic_profile"].is_complete is False
    assert by_key["permissions_configured"].is_complete is True
    assert by_key["first_patient"].is_complete is False


def test_clinic_checklist_denies_non_admin() -> None:
    clinic = ClinicFactory.create()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )

    with pytest.raises(PermissionDenied):
        onboarding_selectors.clinic_onboarding_checklist(
            clinic_id=clinic.pk, actor=therapist
        )


def test_patient_records_goals_and_preferences() -> None:
    clinic = ClinicFactory.create()
    user, profile = _linked_patient(clinic)

    onboarding = onboarding_services.record_patient_onboarding(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        goals=["Reduzir a ansiedade", "Dormir melhor"],
        contact_preferences={"email": True, "phone": False, "whatsapp": False},
        reminder_windows={"morning": True, "afternoon": False, "evening": True},
        current_step="preferences",
        request_id=uuid4(),
    )

    assert onboarding.goals == ["Reduzir a ansiedade", "Dormir melhor"]
    assert onboarding.current_step == "preferences"
    assert onboarding.completed_at is None


def test_patient_onboarding_denies_other_identity() -> None:
    clinic = ClinicFactory.create()
    owner, profile = _linked_patient(clinic)
    other_user, _other_profile = _linked_patient(
        clinic, email="outro@example.test", phone="+55 11 98888-0000"
    )

    with pytest.raises(PermissionDenied):
        onboarding_services.record_patient_onboarding(
            clinic_id=clinic.pk,
            actor=other_user,
            patient_profile_id=profile.pk,
            goals=["Invadir outro perfil"],
            contact_preferences={},
            reminder_windows={},
            current_step="goals",
            request_id=uuid4(),
        )


def test_patient_onboarding_http_stepped_flow(client: Client) -> None:
    clinic = ClinicFactory.create()
    user, profile = _linked_patient(clinic)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("patient_onboarding"),
        {"step": "goals", "goals": "Dormir melhor\nReduzir ansiedade"},
    )
    assert response.status_code == 302
    assert "step=preferences" in response.headers["Location"]

    response = client.post(
        reverse("patient_onboarding"),
        {
            "step": "preferences",
            "contact_preferences": ["email"],
            "reminder_windows": ["morning", "evening"],
        },
    )
    assert response.status_code == 302
    assert "step=terms" in response.headers["Location"]

    terms = client.get(reverse("patient_onboarding"), {"step": "terms"})
    lowered = terms.content.decode().casefold()
    assert "emergência" in lowered
    assert "não substitui" in lowered

    response = client.post(reverse("patient_onboarding"), {"step": "terms"})
    assert response.status_code == 302
    assert "step=complete" in response.headers["Location"]

    onboarding = PatientOnboarding.infrastructure_objects.filter(
        clinic_id=clinic.pk, patient_profile=profile
    ).get()
    assert onboarding.completed_at is not None
    assert onboarding.goals == ["Dormir melhor", "Reduzir ansiedade"]
    assert onboarding.contact_preferences == {
        "email": True,
        "phone": False,
        "whatsapp": False,
    }
    assert onboarding.reminder_windows == {
        "morning": True,
        "afternoon": False,
        "evening": True,
    }


def test_patient_onboarding_resumes_at_current_step(client: Client) -> None:
    clinic = ClinicFactory.create()
    user, profile = _linked_patient(clinic)
    onboarding_services.record_patient_onboarding(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        goals=["Um objetivo"],
        contact_preferences={},
        reminder_windows={},
        current_step="preferences",
        request_id=uuid4(),
    )
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("patient_onboarding"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Preferências de contato" in content
