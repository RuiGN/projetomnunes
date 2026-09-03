"""Acceptance tests for PRD 8.5.5 therapist dashboard."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from people import services as people_services
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from therapist_dashboard.selectors import therapist_dashboard_snapshot

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


def _payload(email: str, phone: str) -> PatientPayload:
    return {
        "full_name": "Paciente Exemplo",
        "social_name": "",
        "birth_date": date(1990, 1, 1),
        "gender": "undisclosed",
        "email": email,
        "phone": phone,
        "language_code": "pt-BR",
        "timezone_name": "America/Sao_Paulo",
        "accessibility_preferences": "",
        "address": {},
        "address_purpose": "",
        "emergency_contact": {},
        "emergency_contact_purpose": "",
    }


def _therapist_and_admin(clinic: Clinic) -> tuple[User, User]:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    return administrator, therapist


def _link_patient(
    clinic: Clinic,
    administrator: User,
    therapist: User,
    *,
    email: str,
    phone: str,
) -> None:
    profile = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_payload(email, phone),
    )
    people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=therapist.pk,
        patient_profile_id=profile.pk,
        function="primary_therapist",
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )


def test_snapshot_counts_linked_patients_and_pending_consents() -> None:
    clinic = ClinicFactory.create()
    administrator, therapist = _therapist_and_admin(clinic)
    _link_patient(
        clinic,
        administrator,
        therapist,
        email="um@example.test",
        phone="+55 11 99999-0001",
    )
    _link_patient(
        clinic,
        administrator,
        therapist,
        email="dois@example.test",
        phone="",
    )

    snapshot = therapist_dashboard_snapshot(clinic_id=clinic.pk, actor=therapist)

    assert snapshot.active_patients == 2
    assert snapshot.new_links == 2
    assert snapshot.incomplete_registrations == 1
    assert snapshot.pending_consents == 0  # nenhum paciente tem conta vinculada
    assert len(snapshot.registration_series) == 6


def test_snapshot_denies_non_therapist() -> None:
    clinic = ClinicFactory.create()
    administrator, _therapist = _therapist_and_admin(clinic)

    with pytest.raises(PermissionDenied):
        therapist_dashboard_snapshot(clinic_id=clinic.pk, actor=administrator)


def test_dashboard_http_renders_cards_table_and_chart(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator, therapist = _therapist_and_admin(clinic)
    _link_patient(
        clinic,
        administrator,
        therapist,
        email="um@example.test",
        phone="+55 11 99999-0001",
    )
    client.force_login(therapist)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("therapist_dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Pacientes ativos vinculados" in content
    assert "Consentimentos pendentes" in content
    assert "Cadastros por período" in content
    assert "Paciente Exemplo" in content
    assert "registration-series" in content
