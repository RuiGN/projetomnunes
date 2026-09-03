"""Acceptance tests for PRD 8.6.5 human triage for configured signals."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import accept_invitation
from clinics.models import Clinic, ClinicMembership
from journal import services as journal_services
from journal.models import (
    ClinicalSignalRule,
    HumanTriageItem,
)
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


def _force_patient_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def _answers(anxiety: int) -> dict[str, object]:
    return {
        "general_state": 3,
        "anxiety": anxiety,
        "sadness": 2,
        "irritability": 2,
        "energy": 3,
        "sleep_quality": 4,
        "motivation": 3,
        "notes": "",
    }


def test_admin_configures_signal_rule() -> None:
    """8.6.5.1: Clinic admin configures thresholds and windows."""
    clinic = ClinicFactory.create()
    administrator, _user, _profile = _linked_patient(clinic)

    rule = journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )

    assert rule.is_active is True
    assert rule.question_key == "anxiety"
    assert rule.threshold == 4
    assert rule.authorized_by_id == administrator.pk


def test_non_admin_cannot_configure_rule() -> None:
    """8.6.5.1: Only clinic admins can configure rules."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)

    with pytest.raises(PermissionDenied):
        journal_services.configure_clinical_signal_rule(
            clinic_id=clinic.pk,
            actor=user,
            name="Regra",
            question_key="anxiety",
            operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
            threshold=4,
            request_id=uuid4(),
        )


def test_rule_rejects_invalid_threshold_and_operator() -> None:
    """8.6.5.1: Deterministic rule validation."""
    clinic = ClinicFactory.create()
    administrator, _user, _profile = _linked_patient(clinic)

    with pytest.raises(ValidationError, match="limiar"):
        journal_services.configure_clinical_signal_rule(
            clinic_id=clinic.pk,
            actor=administrator,
            name="Teste",
            question_key="anxiety",
            operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
            threshold=9,
            request_id=uuid4(),
        )

    with pytest.raises(ValidationError, match="Operador inválido"):
        journal_services.configure_clinical_signal_rule(
            clinic_id=clinic.pk,
            actor=administrator,
            name="Teste",
            question_key="anxiety",
            operator="invalid_op",
            threshold=4,
            request_id=uuid4(),
        )


def test_triage_item_generated_for_matching_answer() -> None:
    """8.6.5.2: Matching answers create a pending human triage item only."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )

    # Check-in with anxiety=4 meets the rule (>=4)
    items = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=4),
        request_id=uuid4(),
    )

    assert len(items) == 1
    item = items[0]
    assert item.status == HumanTriageItem.Status.PENDING
    assert item.is_emergency is False
    assert "anxiety" in item.reason
    assert "Ansiedade elevada" in item.reason

    # Idempotent re-evaluation does not duplicate
    repeated = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=4),
        request_id=uuid4(),
    )
    assert len(repeated) == 1
    assert repeated[0].pk == item.pk


def test_triage_not_generated_when_below_threshold() -> None:
    """8.6.5.2: Answers below the threshold generate no items."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )

    items = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=2),
        request_id=uuid4(),
    )
    assert items == []


def test_triage_ignores_unanswered_questions() -> None:
    """8.6.5.2: Missing answers do not trigger false signals."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )

    answers: dict[str, object] = {"general_state": 3, "anxiety": None}
    items = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=answers,
        request_id=uuid4(),
    )
    assert items == []


def test_therapist_reviews_and_closes_triage_item() -> None:
    """8.6.5.4: Human review with decision and auditor registration."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )
    items = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=5),
        request_id=uuid4(),
    )
    assert len(items) == 1

    reviewed = journal_services.review_human_triage_item(
        clinic_id=clinic.pk,
        actor=therapist,
        triage_item_id=items[0].pk,
        decision="Contato telefônico realizado; paciente estável.",
        request_id=uuid4(),
    )
    assert reviewed.status == HumanTriageItem.Status.CLOSED
    assert reviewed.reviewed_by_id == therapist.pk
    assert reviewed.review_decision == "Contato telefônico realizado; paciente estável."
    assert reviewed.reviewed_at is not None


def test_patient_cannot_review_triage_item() -> None:
    """8.6.5.4: Only authorized therapists review triage items."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Ansiedade elevada",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )
    journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=5),
        request_id=uuid4(),
    )
    item = HumanTriageItem.infrastructure_objects.first()
    assert item is not None

    with pytest.raises(PermissionDenied):
        journal_services.review_human_triage_item(
            clinic_id=clinic.pk,
            actor=user,
            triage_item_id=item.pk,
            decision="Autorevisão indevida",
            request_id=uuid4(),
        )


def test_expired_rule_does_not_generate_triage() -> None:
    """8.6.5.1: Rules respect validity windows (vigência)."""
    from datetime import timedelta

    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    yesterday = date.today() - timedelta(days=1)
    two_days_ago = date.today() - timedelta(days=2)

    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic.pk,
        actor=administrator,
        name="Regra vencida",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        valid_from=two_days_ago,
        valid_until=yesterday,
        request_id=uuid4(),
    )

    items = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_answers(anxiety=5),
        request_id=uuid4(),
    )
    assert items == []


def test_cross_clinic_rule_isolation() -> None:
    """8.6.5.4: Rules and triage remain isolated per clinic."""
    clinic_a = ClinicFactory.create()
    clinic_b = ClinicFactory.create()
    admin_a, user_a, profile_a = _linked_patient(clinic_a)
    _admin_b, user_b, profile_b = _linked_patient(clinic_b, email="b@example.test")
    journal_services.configure_clinical_signal_rule(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        name="Ansiedade clínica A",
        question_key="anxiety",
        operator=ClinicalSignalRule.Operator.GREATER_OR_EQUAL,
        threshold=4,
        request_id=uuid4(),
    )

    # Clinic A rules do not evaluate clinic B patient
    items_b = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic_b.pk,
        actor=user_b,
        patient_profile_id=profile_b.pk,
        answers=_answers(anxiety=5),
        request_id=uuid4(),
    )
    assert items_b == []

    # Clinic A evaluation works
    items_a = journal_services.evaluate_checkin_signal_rules(
        clinic_id=clinic_a.pk,
        actor=user_a,
        patient_profile_id=profile_a.pk,
        answers=_answers(anxiety=5),
        request_id=uuid4(),
    )
    assert len(items_a) == 1


def test_persistent_emergency_notice_on_checkin_ui(client: Client) -> None:
    """8.6.5.3: Patient-facing check-in shows persistent non-emergency warning."""
    clinic = ClinicFactory.create()
    administrator, user, _profile = _linked_patient(clinic)
    journal_services.get_or_create_default_checkin_questionnaire(
        clinic_id=clinic.pk, actor=administrator, request_id=uuid4()
    )
    _force_patient_client(client, clinic, user)

    res = client.get(reverse("checkin_today"))
    assert res.status_code == 200
    content = res.content.decode()
    assert "não atende emergências" in content
    assert "serviços de emergência" in content
