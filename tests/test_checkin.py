"""Acceptance tests for PRD 8.6.4 configurable daily check-in."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.services import accept_invitation
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from journal import services as journal_services
from journal.models import DailyCheckIn
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


def _activate_default_questionnaire(clinic: Clinic, administrator: User) -> None:
    journal_services.get_or_create_default_checkin_questionnaire(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
    )


def _valid_answers() -> dict[str, object]:
    return {
        "general_state": 3,
        "anxiety": 4,
        "sadness": 2,
        "irritability": 2,
        "energy": 3,
        "sleep_quality": 4,
        "motivation": 3,
        "notes": "Dia tranquilo, com um pouco de cansaço.",
    }


# ---------------------------------------------------------------------------
# 8.6.4.1 Questionnaire modeling tests
# ---------------------------------------------------------------------------


def test_default_questionnaire_has_standard_questions() -> None:
    """8.6.4.1: Default questionnaire contains the standard 8 items."""
    clinic = ClinicFactory.create()
    administrator, _user, _profile = _linked_patient(clinic)

    questionnaire = journal_services.get_or_create_default_checkin_questionnaire(
        clinic_id=clinic.pk,
        actor=administrator,
        request_id=uuid4(),
    )

    assert questionnaire.is_active is True
    assert questionnaire.version == "v1.0"
    keys = [q["key"] for q in questionnaire.questions]
    assert keys == [
        "general_state",
        "anxiety",
        "sadness",
        "irritability",
        "energy",
        "sleep_quality",
        "motivation",
        "notes",
    ]
    assert all(q["type"] == "scale_1_5" for q in questionnaire.questions[:7])


def test_patient_cannot_configure_questionnaire() -> None:
    """8.6.4.1: Only clinic admins can configure questionnaires."""
    from django.core.exceptions import PermissionDenied

    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)

    with pytest.raises(PermissionDenied):
        journal_services.get_or_create_default_checkin_questionnaire(
            clinic_id=clinic.pk,
            actor=user,
            request_id=uuid4(),
        )

    # Without an active questionnaire, patient submission fails with validation
    with pytest.raises(ValidationError, match="Nenhum questionário"):
        journal_services.submit_daily_checkin(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            answers=_valid_answers(),
            request_id=uuid4(),
        )


def test_new_questionnaire_version_deactivates_previous() -> None:
    """8.6.4.1: Publishing a new version deactivates the previous active one."""
    clinic = ClinicFactory.create()
    administrator, _user, _profile = _linked_patient(clinic)
    _first = journal_services.get_or_create_default_checkin_questionnaire(
        clinic_id=clinic.pk, actor=administrator, request_id=uuid4()
    )

    new_questions = [
        {
            "key": "general_state",
            "label": "Estado geral",
            "type": "scale_1_5",
            "required": True,
        },
    ]
    second = journal_services.configure_checkin_questionnaire(
        clinic_id=clinic.pk,
        actor=administrator,
        questions=new_questions,
        title="Check-in v2",
        version="v2.0",
        request_id=uuid4(),
    )

    assert second.version == "v2.0"
    assert second.is_active is True
    _first.refresh_from_db()
    assert _first.is_active is False


def test_configure_questionnaire_rejects_duplicate_keys() -> None:
    """8.6.4.1: Question configuration validation."""
    clinic = ClinicFactory.create()
    administrator, _user, _profile = _linked_patient(clinic)

    duplicated = [
        {"key": "same", "label": "Um", "type": "scale_1_5", "required": True},
        {"key": "same", "label": "Dois", "type": "scale_1_5", "required": True},
    ]
    with pytest.raises(ValidationError, match="único"):
        journal_services.configure_checkin_questionnaire(
            clinic_id=clinic.pk,
            actor=administrator,
            questions=duplicated,
            title="Teste",
            version="v2.0",
            request_id=uuid4(),
        )

    invalid_type = [
        {"key": "x", "label": "X", "type": "matrix", "required": True},
    ]
    with pytest.raises(ValidationError, match="Tipo de pergunta inválido"):
        journal_services.configure_checkin_questionnaire(
            clinic_id=clinic.pk,
            actor=administrator,
            questions=invalid_type,
            title="Teste",
            version="v2.0",
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.6.4.2 / 8.6.4.4 Check-in submission tests
# ---------------------------------------------------------------------------


def test_patient_submits_daily_checkin_idempotently() -> None:
    """8.6.4.2 & 8.6.4.4: Idempotent submission per period."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)

    request_id = uuid4()
    first = journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="abc-123",
        request_id=request_id,
    )
    assert first.answers["general_state"] == 3
    assert first.is_draft is False

    # Repeated POST with the same idempotency key does not duplicate
    repeated = journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="abc-123",
        request_id=uuid4(),
    )
    assert repeated.pk == first.pk
    assert (
        DailyCheckIn.infrastructure_objects.filter(
            clinic_id=clinic.pk, patient_profile_id=profile.pk
        ).count()
        == 1
    )


def test_checkin_rejects_invalid_scale_values() -> None:
    """8.6.4.4: Invalid scale answers are rejected with clear messages."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)

    answers = _valid_answers()
    answers["anxiety"] = 9
    with pytest.raises(ValidationError, match="entre 1 e 5"):
        journal_services.submit_daily_checkin(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            answers=answers,
            request_id=uuid4(),
        )

    answers = _valid_answers()
    answers["anxiety"] = "não_sei"
    with pytest.raises(ValidationError, match="Resposta inválida"):
        journal_services.submit_daily_checkin(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            answers=answers,
            request_id=uuid4(),
        )


def test_checkin_update_within_window_preserves_previous_version() -> None:
    """8.6.4.3: Editing within the window preserves the prior version for audit."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)

    first = journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="k1",
        request_id=uuid4(),
    )

    updated_answers = _valid_answers()
    updated_answers["general_state"] = 5
    updated = journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=updated_answers,
        idempotency_key="k2",
        request_id=uuid4(),
    )

    assert updated.pk == first.pk
    assert updated.answers["general_state"] == 5
    assert updated.previous_version_answers is not None
    assert updated.previous_version_answers["general_state"] == 3


def test_draft_checkin_resumes_safely() -> None:
    """8.6.4.4: Interruption with safe draft resumption."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)

    partial: dict[str, object] = {"general_state": 2}
    draft = journal_services.save_draft_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=partial,
        request_id=uuid4(),
    )
    assert draft.is_draft is True
    assert draft.submitted_at is None

    # Draft remains a single row, then submitted normally
    submitted = journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="final",
        request_id=uuid4(),
    )
    assert submitted.pk == draft.pk
    assert submitted.is_draft is False
    assert submitted.submitted_at is not None
    assert (
        DailyCheckIn.infrastructure_objects.filter(
            clinic_id=clinic.pk, patient_profile_id=profile.pk
        ).count()
        == 1
    )


def test_checkin_denied_without_active_questionnaire_and_cross_clinic() -> None:
    """8.6.4.4: Disabled questionnaire and cross-tenant denial."""
    clinic = ClinicFactory.create()
    other_clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    other_admin, other_user, other_profile = _linked_patient(
        other_clinic, email="outro@example.test"
    )
    _activate_default_questionnaire(clinic, administrator)

    # Cross-clinic submission is denied (other patient has no questionnaire)
    with pytest.raises(ValidationError, match="Nenhum questionário"):
        journal_services.submit_daily_checkin(
            clinic_id=other_clinic.pk,
            actor=other_user,
            patient_profile_id=other_profile.pk,
            answers=_valid_answers(),
            request_id=uuid4(),
        )

    # With active questionnaire but wrong patient identity
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        journal_services.submit_daily_checkin(
            clinic_id=clinic.pk,
            actor=other_user,
            patient_profile_id=profile.pk,
            answers=_valid_answers(),
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# HTTP acceptance tests
# ---------------------------------------------------------------------------


def test_checkin_http_flow_submit_and_history(client: Client) -> None:
    """8.6.4.2 & 8.6.4.3: HTTP check-in with progress and history."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)
    _force_patient_client(client, clinic, user)

    # GET today's check-in form
    get_res = client.get(reverse("checkin_today"))
    assert get_res.status_code == 200
    content = get_res.content.decode()
    assert "Check-in Diário" in content
    assert "Prefiro não responder" in content
    assert 'role="progressbar"' in content

    # POST with idempotency key
    post_data = dict(_valid_answers())
    post_data["idempotency_key"] = "http-key-1"
    post_res = client.post(reverse("checkin_today"), data=post_data)
    assert post_res.status_code == 302

    checkin = DailyCheckIn.infrastructure_objects.get(
        clinic_id=clinic.pk, patient_profile_id=profile.pk
    )
    assert checkin.answers["general_state"] == 3

    # History shows the entry
    history = client.get(reverse("checkin_list"))
    assert history.status_code == 200
    history_content = history.content.decode()
    assert "Histórico de Check-ins" in history_content
    assert "Enviado" in history_content

    # Re-POST with same idempotency key does not duplicate
    client.post(reverse("checkin_today"), data=post_data)
    assert (
        DailyCheckIn.infrastructure_objects.filter(
            clinic_id=clinic.pk, patient_profile_id=profile.pk
        ).count()
        == 1
    )


def test_checkin_http_unavailable_without_questionnaire(client: Client) -> None:
    """8.6.4.4: Questionnaire deactivated shows accessible empty state."""
    clinic = ClinicFactory.create()
    _administrator, user, _profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    res = client.get(reverse("checkin_today"))
    assert res.status_code == 200
    assert "Check-in indisponível" in res.content.decode()


def test_checkin_requires_authentication(client: Client) -> None:
    """8.6.4.4: Anonymous access is redirected to login."""
    anon_client = Client()
    res = anon_client.get(reverse("checkin_today"))
    assert res.status_code == 302


def test_checkin_submission_is_audited() -> None:
    """8.6.4.3: Submission and update generate audit events."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    _activate_default_questionnaire(clinic, administrator)

    journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="audit-1",
        request_id=uuid4(),
    )
    journal_services.submit_daily_checkin(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        answers=_valid_answers(),
        idempotency_key="audit-2",
        request_id=uuid4(),
    )

    audit_exists = AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        resource_type="daily_checkin",
    ).exists()
    assert audit_exists
