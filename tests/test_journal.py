"""Acceptance tests for PRD 8.6.1 and 8.6.2 journal entries and UI experience."""

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
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from journal import selectors as journal_selectors
from journal import services as journal_services
from journal.forms import JournalEntryForm, JournalFilterForm
from journal.models import (
    CONTEXT_MAX_LENGTH,
    DETAIL_MAX_LENGTH,
    JournalAccessRequest,
    JournalEntry,
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


class EntryKwargs(TypedDict):
    mood: int
    emotions: list[str]
    intensity: int
    context: str
    triggers: str
    reactions: str
    strategies: str
    visibility: str


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


def _entry_kwargs() -> EntryKwargs:
    return {
        "mood": JournalEntry.Mood.LOW,
        "emotions": ["anxiety", "sadness"],
        "intensity": 3,
        "context": "Dia difícil no trabalho.",
        "triggers": "Reunião tensa.",
        "reactions": "Coração acelerado.",
        "strategies": "Respirei fundo.",
        "visibility": JournalEntry.Visibility.PRIVATE,
    }


def _force_patient_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


# ---------------------------------------------------------------------------
# 8.6.1 Domain and Privacy Tests
# ---------------------------------------------------------------------------


def test_patient_creates_journal_entry_with_visibility() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)

    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **_entry_kwargs(),
    )

    assert isinstance(entry, JournalEntry)
    assert entry.author_id == user.pk
    assert entry.patient_profile_id == profile.pk
    assert entry.mood == JournalEntry.Mood.LOW
    assert entry.emotions == ["anxiety", "sadness"]
    assert entry.intensity == 3
    assert entry.visibility == JournalEntry.Visibility.PRIVATE


def test_journal_entry_rejects_invalid_intensity_and_emotion() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)

    payload = _entry_kwargs()
    payload["intensity"] = 6
    with pytest.raises(ValidationError, match="intensidade"):
        journal_services.create_journal_entry(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            request_id=uuid4(),
            **payload,
        )

    payload = _entry_kwargs()
    payload["emotions"] = ["nao_existe"]
    with pytest.raises(ValidationError, match="emoções"):
        journal_services.create_journal_entry(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            request_id=uuid4(),
            **payload,
        )


def test_visibility_change_is_audited() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **_entry_kwargs(),
    )

    changed = journal_services.set_journal_entry_visibility(
        clinic_id=clinic.pk,
        actor=user,
        journal_entry_id=entry.pk,
        visibility=JournalEntry.Visibility.SHAREABLE,
        request_id=uuid4(),
    )

    assert changed.visibility == JournalEntry.Visibility.SHAREABLE
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        resource_type="journal_entry",
        resource_id=str(entry.pk),
    ).exists()


def test_therapist_visible_entries_exclude_private_and_confirmation_required() -> None:
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
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
    shareable_payload = _entry_kwargs()
    shareable_payload["visibility"] = JournalEntry.Visibility.SHAREABLE
    shareable = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **shareable_payload,
    )
    yellow_payload = _entry_kwargs()
    yellow_payload["visibility"] = JournalEntry.Visibility.CONFIRMATION_REQUIRED
    journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **yellow_payload,
    )
    private_payload = _entry_kwargs()
    private_payload["visibility"] = JournalEntry.Visibility.PRIVATE
    journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **private_payload,
    )

    visible = journal_selectors.therapist_visible_journal_entries(
        clinic_id=clinic.pk, therapist_id=therapist.pk
    )

    assert [entry.pk for entry in visible] == [shareable.pk]


def test_journal_denies_other_patient_and_unlinked_therapist() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _administrator, other_user, _other_profile = _linked_patient(
        clinic, email="outro@example.test"
    )
    entry_payload = _entry_kwargs()
    entry_payload["visibility"] = JournalEntry.Visibility.SHAREABLE
    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **entry_payload,
    )

    with pytest.raises(PermissionDenied):
        journal_services.set_journal_entry_visibility(
            clinic_id=clinic.pk,
            actor=other_user,
            journal_entry_id=entry.pk,
            visibility=JournalEntry.Visibility.PRIVATE,
            request_id=uuid4(),
        )

    unlinked_therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=unlinked_therapist, role=ClinicMembership.Role.THERAPIST
    )
    visible = journal_selectors.therapist_visible_journal_entries(
        clinic_id=clinic.pk, therapist_id=unlinked_therapist.pk
    )
    assert visible == []


def test_journal_entry_rejects_oversized_text() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)

    payload = _entry_kwargs()
    payload["context"] = "x" * (CONTEXT_MAX_LENGTH + 1)
    with pytest.raises(ValidationError):
        journal_services.create_journal_entry(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            request_id=uuid4(),
            **payload,
        )

    payload = _entry_kwargs()
    payload["triggers"] = "x" * (DETAIL_MAX_LENGTH + 1)
    with pytest.raises(ValidationError):
        journal_services.create_journal_entry(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            request_id=uuid4(),
            **payload,
        )


def test_journal_update_limited_to_author() -> None:
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _administrator, other_user, _other_profile = _linked_patient(
        clinic, email="outro@example.test"
    )
    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        request_id=uuid4(),
        **_entry_kwargs(),
    )

    updated = journal_services.update_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        journal_entry_id=entry.pk,
        mood=JournalEntry.Mood.GOOD,
        emotions=["hope"],
        intensity=4,
        context="Atualizado pela própria autora.",
        triggers="",
        reactions="",
        strategies="",
        request_id=uuid4(),
    )

    assert updated.mood == JournalEntry.Mood.GOOD
    assert updated.context == "Atualizado pela própria autora."

    with pytest.raises(PermissionDenied):
        journal_services.update_journal_entry(
            clinic_id=clinic.pk,
            actor=other_user,
            journal_entry_id=entry.pk,
            mood=JournalEntry.Mood.GOOD,
            emotions=["hope"],
            intensity=4,
            context="Tentativa de outro usuário.",
            triggers="",
            reactions="",
            strategies="",
            request_id=uuid4(),
        )


def test_journal_cross_clinic_access_is_denied() -> None:
    clinic_a = ClinicFactory.create()
    _administrator_a, user_a, profile_a = _linked_patient(clinic_a)
    shareable_payload = _entry_kwargs()
    shareable_payload["visibility"] = JournalEntry.Visibility.SHAREABLE
    entry_a = journal_services.create_journal_entry(
        clinic_id=clinic_a.pk,
        actor=user_a,
        patient_profile_id=profile_a.pk,
        request_id=uuid4(),
        **shareable_payload,
    )

    clinic_b = ClinicFactory.create()
    _administrator_b, user_b, _profile_b = _linked_patient(
        clinic_b, email="b@example.test"
    )
    therapist_b = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic_b, user=therapist_b, role=ClinicMembership.Role.THERAPIST
    )

    # Patient B cannot read clinic A's journal.
    assert (
        journal_selectors.patient_journal_entries(clinic_id=clinic_a.pk, actor=user_b)
        == []
    )

    # Therapist B is denied clinic A's journal.
    with pytest.raises(PermissionDenied):
        journal_selectors.therapist_visible_journal_entries(
            clinic_id=clinic_a.pk, therapist_id=therapist_b.pk
        )

    # Patient B cannot mutate clinic A's entries.
    with pytest.raises(PermissionDenied):
        journal_services.set_journal_entry_visibility(
            clinic_id=clinic_a.pk,
            actor=user_b,
            journal_entry_id=entry_a.pk,
            visibility=JournalEntry.Visibility.PRIVATE,
            request_id=uuid4(),
        )

    with pytest.raises(PermissionDenied):
        journal_services.create_journal_entry(
            clinic_id=clinic_a.pk,
            actor=user_b,
            patient_profile_id=profile_a.pk,
            request_id=uuid4(),
            **shareable_payload,
        )


# ---------------------------------------------------------------------------
# 8.6.2 Forms and UI Acceptance Tests
# ---------------------------------------------------------------------------


def test_journal_entry_form_validation() -> None:
    """8.6.2.1: Test form validation for fields and text limits."""
    # Valid form
    valid_data = {
        "mood": JournalEntry.Mood.GOOD,
        "emotions": ["joy", "calm"],
        "intensity": 4,
        "context": "Hoje foi um bom dia de trabalho.",
        "triggers": "Concluí um projeto importante.",
        "reactions": "Sensação de alívio e leveza.",
        "strategies": "Comemorei com amigos.",
        "visibility": JournalEntry.Visibility.SHAREABLE,
    }
    form = JournalEntryForm(data=valid_data)
    assert form.is_valid(), form.errors

    # Invalid mood
    invalid_data = dict(valid_data, mood=99)
    form = JournalEntryForm(data=invalid_data)
    assert not form.is_valid()
    assert "mood" in form.errors

    # Invalid intensity (out of bounds)
    invalid_data = dict(valid_data, intensity=0)
    form = JournalEntryForm(data=invalid_data)
    assert not form.is_valid()
    assert "intensity" in form.errors

    # Missing required context
    invalid_data = dict(valid_data, context="   ")
    form = JournalEntryForm(data=invalid_data)
    assert not form.is_valid()
    assert "context" in form.errors

    # Oversized context
    invalid_data = dict(valid_data, context="A" * (CONTEXT_MAX_LENGTH + 1))
    form = JournalEntryForm(data=invalid_data)
    assert not form.is_valid()
    assert "context" in form.errors

    # Oversized triggers
    invalid_data = dict(valid_data, triggers="A" * (DETAIL_MAX_LENGTH + 1))
    form = JournalEntryForm(data=invalid_data)
    assert not form.is_valid()
    assert "triggers" in form.errors


def test_journal_filter_form_defaults() -> None:
    """8.6.2.3: Test filter form options and defaults."""
    form = JournalFilterForm(data={"period": "7d", "emotion": "joy", "mood": "4"})
    assert form.is_valid()
    assert form.cleaned_data["period"] == "7d"
    assert form.cleaned_data["emotion"] == "joy"
    assert form.cleaned_data["mood"] == "4"


def test_patient_journal_calendar_selector() -> None:
    """8.6.2.2: Test calendar data generator with legend, matrix, and summary."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)

    # Create entries on different dates
    journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.VERY_GOOD,
        emotions=["joy", "hope"],
        intensity=5,
        context="Dia maravilhoso com a família.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.PRIVATE,
        request_id=uuid4(),
    )

    calendar_data = journal_selectors.patient_journal_calendar_data(
        clinic_id=clinic.pk,
        actor=user,
        year=date.today().year,
        month=date.today().month,
    )

    assert calendar_data.year == date.today().year
    assert calendar_data.month == date.today().month
    assert len(calendar_data.days_header) == 7
    assert len(calendar_data.legend) == 5
    assert len(calendar_data.weeks) >= 4

    # Check that today's cell has dominant mood and accessible label
    today_found = False
    for week in calendar_data.weeks:
        for day in week:
            if day.is_today:
                today_found = True
                assert day.entry_count >= 1
                assert day.dominant_mood == JournalEntry.Mood.VERY_GOOD
                assert "Humor Muito bem" in day.accessible_label
    assert today_found


def test_journal_views_create_and_list_flow(client: Client) -> None:
    """8.6.2.1 & 8.6.2.3: Test creating a journal entry and listing it via HTTP."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    # GET Create form
    get_res = client.get(reverse("journal_create"))
    assert get_res.status_code == 200
    assert "Novo Registro no Diário" in get_res.content.decode()
    assert "Como você está se sentindo?" in get_res.content.decode()
    assert "Verde — Compartilhável" in get_res.content.decode()

    # POST Create valid entry
    post_data = {
        "mood": JournalEntry.Mood.GOOD,
        "emotions": ["calm", "hope"],
        "intensity": 4,
        "context": "Hoje fiz uma caminhada e me senti muito melhor.",
        "triggers": "Ar puro e sol.",
        "reactions": "Respiração profunda e tranquila.",
        "strategies": "Atenção plena ao caminhar.",
        "visibility": JournalEntry.Visibility.CONFIRMATION_REQUIRED,
    }
    post_res = client.post(reverse("journal_create"), data=post_data)
    assert post_res.status_code == 302
    assert post_res["Location"] == reverse("journal_list")

    # Verify created entry in database
    entry = JournalEntry.objects.for_clinic(clinic.pk).first()
    assert entry is not None
    assert entry.mood == JournalEntry.Mood.GOOD
    assert entry.visibility == JournalEntry.Visibility.CONFIRMATION_REQUIRED
    assert entry.context == "Hoje fiz uma caminhada e me senti muito melhor."

    # GET List view
    list_res = client.get(reverse("journal_list"))
    assert list_res.status_code == 200
    content = list_res.content.decode()
    assert "Diário Emocional" in content
    assert "Calendário Emocional" in content
    assert "Hoje fiz uma caminhada" in content
    assert "Amarelo — Confirmar antes" in content
    assert "Legenda:" in content


def test_journal_views_validation_error_rendering(client: Client) -> None:
    """8.6.2.4: Test accessible error summary rendering on invalid POST."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    # POST Invalid entry (missing context)
    invalid_post_data = {
        "mood": JournalEntry.Mood.NEUTRAL,
        "intensity": 3,
        "context": "",
        "visibility": JournalEntry.Visibility.PRIVATE,
    }
    response = client.post(reverse("journal_create"), data=invalid_post_data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Revise os campos indicados" in content
    assert "form-error-summary" in content


def test_journal_detail_and_edit_flow(client: Client) -> None:
    """8.6.2.3: Test detail view, edit view, and visibility toggle."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.LOW,
        emotions=["sadness"],
        intensity=2,
        context="Relato inicial com sentimento de tristeza.",
        triggers="Notícia desagradável.",
        reactions="Cansaço.",
        strategies="Descansei.",
        visibility=JournalEntry.Visibility.PRIVATE,
        request_id=uuid4(),
    )

    # Detail view
    detail_res = client.get(reverse("journal_detail", args=[entry.pk]))
    assert detail_res.status_code == 200
    detail_content = detail_res.content.decode()
    assert "Relato inicial com sentimento de tristeza." in detail_content
    assert "Vermelho — Somente você" in detail_content
    assert "Notícia desagradável." in detail_content

    # Edit GET
    edit_get = client.get(reverse("journal_edit", args=[entry.pk]))
    assert edit_get.status_code == 200
    assert "Editar Registro no Diário" in edit_get.content.decode()

    # Edit POST
    edit_post_data = {
        "mood": JournalEntry.Mood.NEUTRAL,
        "emotions": ["calm"],
        "intensity": 3,
        "context": "Relato atualizado após conversa reflexiva.",
        "triggers": "",
        "reactions": "",
        "strategies": "Conversar com amigos.",
        "visibility": JournalEntry.Visibility.SHAREABLE,
    }
    edit_post = client.post(
        reverse("journal_edit", args=[entry.pk]), data=edit_post_data
    )
    assert edit_post.status_code == 302

    entry.refresh_from_db()
    assert entry.mood == JournalEntry.Mood.NEUTRAL
    assert entry.context == "Relato atualizado após conversa reflexiva."
    assert entry.visibility == JournalEntry.Visibility.SHAREABLE

    # Quick set visibility endpoint
    vis_res = client.post(
        reverse("journal_set_visibility", args=[entry.pk]),
        data={"visibility": JournalEntry.Visibility.PRIVATE},
    )
    assert vis_res.status_code == 302
    entry.refresh_from_db()
    assert entry.visibility == JournalEntry.Visibility.PRIVATE


def test_journal_views_security_and_authorization(client: Client) -> None:
    """8.6.2.3: Test that unauthenticated and unauthorized access is denied."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _administrator, other_user, _other_profile = _linked_patient(
        clinic, email="outro@example.test"
    )

    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.GOOD,
        emotions=["joy"],
        intensity=4,
        context="Segredo pessoal do paciente.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.PRIVATE,
        request_id=uuid4(),
    )

    # Anonymous user -> redirected to login
    anon_client = Client()
    anon_res = anon_client.get(reverse("journal_list"))
    assert anon_res.status_code == 302

    # Other patient attempting to view or edit first patient's entry
    _force_patient_client(client, clinic, other_user)
    other_detail = client.get(reverse("journal_detail", args=[entry.pk]))
    assert other_detail.status_code == 403

    other_edit = client.get(reverse("journal_edit", args=[entry.pk]))
    assert other_edit.status_code == 403

    other_edit_post = client.post(
        reverse("journal_edit", args=[entry.pk]),
        data={"context": "Hacked"},
    )
    assert other_edit_post.status_code == 403


def test_journal_history_filtering_and_pagination(client: Client) -> None:
    """8.6.2.3: Test filtering by period/emotion/mood and pagination."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    _force_patient_client(client, clinic, user)

    # Create 12 entries to trigger pagination (10 per page)
    for i in range(12):
        mood = JournalEntry.Mood.GOOD if i % 2 == 0 else JournalEntry.Mood.LOW
        emotion = "joy" if i % 2 == 0 else "sadness"
        journal_services.create_journal_entry(
            clinic_id=clinic.pk,
            actor=user,
            patient_profile_id=profile.pk,
            mood=mood,
            emotions=[emotion],
            intensity=3,
            context=f"Entrada número {i + 1}",
            triggers="",
            reactions="",
            strategies="",
            visibility=JournalEntry.Visibility.PRIVATE,
            request_id=uuid4(),
        )

    # Page 1
    page1_res = client.get(reverse("journal_list"))
    assert page1_res.status_code == 200
    content1 = page1_res.content.decode()
    assert "Página 1 de 2" in content1
    assert "Entrada número 12" in content1

    # Page 2
    page2_res = client.get(f"{reverse('journal_list')}?page=2")
    assert page2_res.status_code == 200
    content2 = page2_res.content.decode()
    assert "Página 2 de 2" in content2
    assert "Entrada número 1" in content2

    # Filter by emotion=joy
    filter_joy = client.get(f"{reverse('journal_list')}?emotion=joy")
    assert filter_joy.status_code == 200
    joy_content = filter_joy.content.decode()
    assert "Entrada número 11" in joy_content
    assert "Entrada número 12" not in joy_content

    # Filter by mood=1 (Muito mal) -> empty state
    filter_empty = client.get(f"{reverse('journal_list')}?mood=1")
    assert filter_empty.status_code == 200
    assert "Nenhum registro encontrado" in filter_empty.content.decode()


# ---------------------------------------------------------------------------
# 8.6.3 Sharing Traffic Light & Access Request Acceptance Tests
# ---------------------------------------------------------------------------


def test_sharing_traffic_light_yellow_request_grant_and_revoke_flow(
    client: Client,
) -> None:
    """8.6.3: Test full flow of yellow request, approval, visibility and revocation."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
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

    # 1. Patient creates Yellow entry
    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.NEUTRAL,
        emotions=["anxiety"],
        intensity=3,
        context="Registro sensível que exige confirmação prévia.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.CONFIRMATION_REQUIRED,
        request_id=uuid4(),
    )

    # 2. Therapist cannot see Yellow entry without active grant
    visible_before = journal_selectors.therapist_visible_journal_entries(
        clinic_id=clinic.pk, therapist_id=therapist.pk
    )
    assert visible_before == []

    # 3. Therapist requests access
    req = journal_services.request_journal_entry_access(
        clinic_id=clinic.pk,
        therapist=therapist,
        journal_entry_id=entry.pk,
        purpose="Acompanhamento e discussão terapêutica",
        expires_at=None,
        request_id=uuid4(),
    )
    assert req.status == JournalAccessRequest.Status.PENDING

    # 4. Patient sees pending request in list
    _force_patient_client(client, clinic, user)
    list_res = client.get(reverse("journal_list"))
    assert list_res.status_code == 200
    assert "Solicitações de Acesso Pendentes (1)" in list_res.content.decode()

    # 5. Patient approves request via HTTP POST
    respond_res = client.post(
        reverse("journal_respond_access_request", args=[req.pk]),
        data={"decision": "approve", "expires_days": "30"},
    )
    assert respond_res.status_code == 302
    req.refresh_from_db()
    assert req.status == JournalAccessRequest.Status.GRANTED
    assert req.expires_at is not None

    # 6. Now therapist query returns the granted Yellow entry
    visible_after_grant = journal_selectors.therapist_visible_journal_entries(
        clinic_id=clinic.pk, therapist_id=therapist.pk
    )
    assert [e.pk for e in visible_after_grant] == [entry.pk]

    # 7. Patient revokes sharing via HTTP POST
    revoke_res = client.post(reverse("journal_revoke_sharing", args=[entry.pk]))
    assert revoke_res.status_code == 302
    entry.refresh_from_db()
    req.refresh_from_db()
    assert entry.visibility == JournalEntry.Visibility.PRIVATE
    assert req.status == JournalAccessRequest.Status.REVOKED

    # 8. Entry immediately vanishes from therapist view
    visible_after_revoke = journal_selectors.therapist_visible_journal_entries(
        clinic_id=clinic.pk, therapist_id=therapist.pk
    )
    assert visible_after_revoke == []


def test_therapist_cannot_request_access_to_private_red_entry() -> None:
    """8.6.3: Therapist cannot request access to a private (Red) entry."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
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

    private_entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.VERY_LOW,
        emotions=["anger"],
        intensity=5,
        context="Privado e estritamente confidencial.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.PRIVATE,
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        journal_services.request_journal_entry_access(
            clinic_id=clinic.pk,
            therapist=therapist,
            journal_entry_id=private_entry.pk,
            purpose="Quero ver",
            expires_at=None,
            request_id=uuid4(),
        )


def test_unlinked_therapist_cannot_request_access_to_yellow_entry() -> None:
    """8.6.3: Unlinked therapist is denied access request to any patient entry."""
    clinic = ClinicFactory.create()
    _administrator, user, profile = _linked_patient(clinic)
    unlinked_therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=unlinked_therapist, role=ClinicMembership.Role.THERAPIST
    )

    yellow_entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.NEUTRAL,
        emotions=["fear"],
        intensity=3,
        context="Entrada amarela de paciente sem vínculo com terapeuta.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.CONFIRMATION_REQUIRED,
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        journal_services.request_journal_entry_access(
            clinic_id=clinic.pk,
            therapist=unlinked_therapist,
            journal_entry_id=yellow_entry.pk,
            purpose="Tentativa sem vínculo",
            expires_at=None,
            request_id=uuid4(),
        )


def test_patient_can_reject_access_request() -> None:
    """8.6.3: Patient can reject an access request."""
    clinic = ClinicFactory.create()
    administrator, user, profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
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

    entry = journal_services.create_journal_entry(
        clinic_id=clinic.pk,
        actor=user,
        patient_profile_id=profile.pk,
        mood=JournalEntry.Mood.NEUTRAL,
        emotions=["calm"],
        intensity=3,
        context="Registro amarelo a ser recusado.",
        triggers="",
        reactions="",
        strategies="",
        visibility=JournalEntry.Visibility.CONFIRMATION_REQUIRED,
        request_id=uuid4(),
    )

    req = journal_services.request_journal_entry_access(
        clinic_id=clinic.pk,
        therapist=therapist,
        journal_entry_id=entry.pk,
        purpose="Discussão clínica",
        expires_at=None,
        request_id=uuid4(),
    )

    rejected = journal_services.respond_journal_entry_access_request(
        clinic_id=clinic.pk,
        actor=user,
        access_request_id=req.pk,
        approved=False,
        request_id=uuid4(),
    )

    assert rejected.status == JournalAccessRequest.Status.REJECTED
    assert (
        journal_selectors.therapist_visible_journal_entries(
            clinic_id=clinic.pk, therapist_id=therapist.pk
        )
        == []
    )
