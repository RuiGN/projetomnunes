"""Acceptance tests for PRD 8.5.3 patient and care-link management."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import accept_invitation
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people import models as people_models
from people import services as people_services
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _clinic_administrator() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, administrator


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
        "email": "MARINA@example.test",
        "phone": "+55 (11) 99999-1234",
        "language_code": "pt-BR",
        "timezone_name": "America/Sao_Paulo",
        "accessibility_preferences": "Prefere instruções por escrito.",
        "address": {},
        "address_purpose": "",
        "emergency_contact": {},
        "emergency_contact_purpose": "",
    }


def test_admin_registers_minimized_tenant_patient_and_blocks_exact_duplicate() -> None:
    clinic, administrator = _clinic_administrator()

    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )

    assert isinstance(patient, people_models.PatientProfile)
    assert patient.clinic_id == clinic.pk
    assert patient.user_id is None
    assert patient.email == "marina@example.test"
    assert patient.phone == "+5511999991234"
    assert patient.gender == "woman"
    assert patient.accessibility_preferences.startswith("Prefere")
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        resource_type="patient_profile",
        resource_id=str(patient.pk),
    ).exists()

    with pytest.raises(ValidationError, match="possível duplicidade"):
        people_services.register_patient_profile(
            clinic_id=clinic.pk,
            actor=administrator,
            request_id=uuid4(),
            **_patient_payload(),
        )


def test_sensitive_patient_contacts_require_purpose_and_cross_tenant_is_denied() -> (
    None
):
    clinic, administrator = _clinic_administrator()
    other_clinic, other_administrator = _clinic_administrator()
    payload = _patient_payload()
    payload["emergency_contact"] = {
        "name": "Contato de confiança",
        "phone": "+5511988880000",
    }

    with pytest.raises(ValidationError, match="finalidade"):
        people_services.register_patient_profile(
            clinic_id=clinic.pk,
            actor=administrator,
            request_id=uuid4(),
            **payload,
        )

    payload["emergency_contact_purpose"] = "Contato solicitado pela paciente."
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **payload,
    )

    with pytest.raises(PermissionDenied):
        people_services.update_patient_profile_contact(
            clinic_id=other_clinic.pk,
            actor=other_administrator,
            patient_profile_id=patient.pk,
            phone="+5511977770000",
            request_id=uuid4(),
        )


def test_patient_invitation_links_existing_profile_without_disclosing_it() -> None:
    clinic, administrator = _clinic_administrator()
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )

    issued = people_services.issue_patient_invitation(
        clinic_id=clinic.pk,
        actor=administrator,
        patient_profile_id=patient.pk,
        expires_at=people_services.invitation_expiration_after(days=2),
        request_id=uuid4(),
    )
    invited_user = accept_invitation(
        raw_token=issued.raw_token,
        password="senha-sintetica-longa-e-nao-reutilizavel",
        first_name="Marina",
        last_name="Exemplo",
    )

    patient.refresh_from_db()
    assert patient.user_id == invited_user.pk
    assert issued.invitation.initial_role == ClinicMembership.Role.PATIENT
    assert issued.invitation.recipient_email == patient.email


def test_admin_creates_and_closes_explicit_patient_professional_link() -> None:
    clinic, administrator = _clinic_administrator()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=therapist,
        role=ClinicMembership.Role.THERAPIST,
    )
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    start = date.today()

    relationship = people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=therapist.pk,
        patient_profile_id=patient.pk,
        function="primary_therapist",
        valid_from=start,
        valid_until=start + timedelta(days=90),
        request_id=uuid4(),
    )

    assert relationship.patient_profile_id == patient.pk
    assert relationship.patient_id is None
    assert relationship.authorized_by_id == administrator.pk
    assert relationship.function == "primary_therapist"
    assert relationship.is_active is True

    closed = people_services.close_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        relationship_id=relationship.pk,
        ended_on=start + timedelta(days=30),
        request_id=uuid4(),
    )
    assert closed.is_active is False
    assert closed.valid_until == start + timedelta(days=30)
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            resource_type="care_relationship",
            resource_id=str(relationship.pk),
        ).count()
        == 2
    )


def test_patient_directory_http_supports_manual_registration(client: Client) -> None:
    clinic, administrator = _clinic_administrator()
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("patient_create"),
        {
            "full_name": "Joana Exemplo",
            "social_name": "Joana",
            "birth_date": "1990-04-12",
            "gender": "undisclosed",
            "email": "joana@example.test",
            "phone": "+55 81 99999-0000",
            "language_code": "pt-BR",
            "timezone_name": "America/Recife",
            "accessibility_preferences": "",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("patient_list")
    listing = client.get(reverse("patient_list"))
    assert listing.status_code == 200
    content = listing.content.decode()
    assert "Joana Exemplo" in content
    assert "Cadastrar paciente" in content
    assert str(clinic.pk) not in content


def test_patient_form_persists_optional_address_and_emergency_contact(
    client: Client,
) -> None:
    clinic, administrator = _clinic_administrator()
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("patient_create"),
        {
            "full_name": "Paula Exemplo",
            "social_name": "Paula",
            "birth_date": "1988-01-10",
            "gender": "undisclosed",
            "email": "paula@example.test",
            "phone": "+55 81 99999-1111",
            "language_code": "pt-BR",
            "timezone_name": "America/Recife",
            "accessibility_preferences": "",
            "address_line": "Rua das Flores, 100",
            "address_city": "Recife",
            "address_state": "PE",
            "address_postal_code": "50000-000",
            "address_purpose": "Endereço para contato administrativo.",
            "emergency_contact_name": "Contato de confiança",
            "emergency_contact_phone": "+55 81 98888-2222",
            "emergency_contact_purpose": "Acionamento apenas em situações urgentes.",
        },
    )

    assert response.status_code == 302
    patient = people_models.PatientProfile.infrastructure_objects.filter(
        clinic_id=clinic.pk, email="paula@example.test"
    ).get()
    assert patient.address == {
        "line": "Rua das Flores, 100",
        "city": "Recife",
        "state": "PE",
        "postal_code": "50000-000",
    }
    assert patient.address_purpose == "Endereço para contato administrativo."
    assert patient.emergency_contact["name"] == "Contato de confiança"
    assert patient.emergency_contact["phone"] == "+55 81 98888-2222"


def test_patient_form_requires_purpose_for_emergency_contact(client: Client) -> None:
    clinic, administrator = _clinic_administrator()
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("patient_create"),
        {
            "full_name": "Paula Exemplo",
            "social_name": "",
            "birth_date": "1988-01-10",
            "gender": "undisclosed",
            "email": "paula@example.test",
            "phone": "",
            "language_code": "pt-BR",
            "timezone_name": "America/Recife",
            "accessibility_preferences": "",
            "emergency_contact_name": "Contato de confiança",
            "emergency_contact_phone": "+55 81 98888-2222",
            "emergency_contact_purpose": "",
        },
    )

    assert response.status_code == 200
    assert "finalidade" in response.content.decode().casefold()
    assert not people_models.PatientProfile.infrastructure_objects.filter(
        clinic_id=clinic.pk
    ).exists()


def test_patient_invite_http_issues_single_use_invitation(client: Client) -> None:
    clinic, administrator = _clinic_administrator()
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("patient_invite", kwargs={"patient_profile_id": patient.pk})
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("patient_list")
    link = people_models.PatientInvitationLink.objects.filter(
        patient_profile=patient
    ).first()
    assert link is not None
    assert link.invitation.initial_role == ClinicMembership.Role.PATIENT
    assert link.invitation.used_at is None
    assert link.invitation.recipient_email == patient.email


def test_transfer_patient_care_relationship_reassigns_and_audits() -> None:
    clinic, administrator = _clinic_administrator()
    first_therapist = UserFactory.create()
    second_therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=first_therapist, role=ClinicMembership.Role.THERAPIST
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=second_therapist, role=ClinicMembership.Role.THERAPIST
    )
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    start = date.today()

    original = people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=first_therapist.pk,
        patient_profile_id=patient.pk,
        function="primary_therapist",
        valid_from=start,
        valid_until=start + timedelta(days=90),
        request_id=uuid4(),
    )

    transferred = people_services.transfer_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        relationship_id=original.pk,
        new_therapist_id=second_therapist.pk,
        transferred_on=start + timedelta(days=10),
        request_id=uuid4(),
    )

    original.refresh_from_db()
    assert original.is_active is False
    assert original.valid_until == start + timedelta(days=10)
    assert transferred.therapist_id == second_therapist.pk
    assert transferred.is_active is True
    assert transferred.function == "primary_therapist"
    assert transferred.patient_profile_id == patient.pk
    assert transferred.authorized_by_id == administrator.pk
    assert transferred.valid_from == start + timedelta(days=10)
    assert transferred.valid_until == start + timedelta(days=90)
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            resource_type="care_relationship",
            resource_id=str(original.pk),
        ).count()
        == 2
    )
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            resource_type="care_relationship",
            resource_id=str(transferred.pk),
        ).count()
        == 1
    )


def test_transfer_patient_care_relationship_requires_therapist_role() -> None:
    clinic, administrator = _clinic_administrator()
    first_therapist = UserFactory.create()
    non_therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=first_therapist, role=ClinicMembership.Role.THERAPIST
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=non_therapist,
        role=ClinicMembership.Role.ADMINISTRATIVE_STAFF,
    )
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    original = people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=first_therapist.pk,
        patient_profile_id=patient.pk,
        function="primary_therapist",
        valid_from=date.today(),
        valid_until=date.today() + timedelta(days=90),
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        people_services.transfer_patient_care_relationship(
            clinic_id=clinic.pk,
            actor=administrator,
            relationship_id=original.pk,
            new_therapist_id=non_therapist.pk,
            transferred_on=date.today() + timedelta(days=10),
            request_id=uuid4(),
        )


def test_therapist_opens_linked_patient_ficha_and_audits(client: Client) -> None:
    clinic, administrator = _clinic_administrator()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=therapist.pk,
        patient_profile_id=patient.pk,
        function="primary_therapist",
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    client.force_login(therapist)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(
        reverse("patient_detail", kwargs={"patient_profile_id": patient.pk})
    )

    assert response.status_code == 200
    assert "Marina Exemplo" in response.content.decode()
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        resource_type="patient_profile",
        resource_id=str(patient.pk),
        action="view",
    ).exists()


def test_therapist_denied_unlinked_patient_ficha(client: Client) -> None:
    clinic, administrator = _clinic_administrator()
    therapist = UserFactory.create()
    other_therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=other_therapist, role=ClinicMembership.Role.THERAPIST
    )
    patient = people_services.register_patient_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
        **_patient_payload(),
    )
    people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=other_therapist.pk,
        patient_profile_id=patient.pk,
        function="primary_therapist",
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    client.force_login(therapist)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(
        reverse("patient_detail", kwargs={"patient_profile_id": patient.pk})
    )

    assert response.status_code == 403
