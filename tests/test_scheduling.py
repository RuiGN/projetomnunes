"""Acceptance tests for PRD 8.8 — agenda, consultas, lembretes e comunicação."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from accounts.models import User
from accounts.services import accept_invitation
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from goals.low_energy_models import LowEnergyMode
from people import services as people_services
from people.models import PatientProfile
from scheduling import services as scheduling_services
from scheduling.delivery_templates import (
    appointment_reminder_message,
    new_message_notification_message,
)
from scheduling.messaging_services import (
    add_attachment,
    create_conversation,
    delete_attachment,
    download_attachment,
    mark_conversation_read,
    send_message,
)
from scheduling.models import (
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
    AvailabilityOverride,
    AvailabilityPattern,
    Conversation,
    ConversationKind,
    Message,
    MessageAttachment,
    ReminderStatus,
    ReminderType,
    Room,
    ScanStatus,
    ScheduleBlock,
    Service,
    Unit,
)
from scheduling.operating_hours import out_of_hours_response, within_operating_hours
from scheduling.reminder_services import (
    cancel_reminders_for_appointment,
    mark_reminder_failed,
    schedule_appointment_reminder,
    schedule_reminder,
    snooze_reminder,
    upsert_reminder_preference,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db

SP_TZ = ZoneInfo("America/Sao_Paulo")


def _payload(email: str) -> dict[str, Any]:
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


def _link_therapist(
    clinic: Clinic, administrator: User, profile: PatientProfile
) -> User:
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
    return therapist


def _service(clinic: Clinic, **overrides: Any) -> Service:
    values: dict[str, Any] = {
        "name": "Sessão individual",
        "duration_minutes": 50,
        "buffer_minutes": 10,
        "is_active": True,
    }
    values.update(overrides)
    return Service.infrastructure_objects.create(clinic_id=clinic.pk, **values)


def _unit(clinic: Clinic, **overrides: Any) -> Unit:
    values: dict[str, Any] = {
        "name": "Unidade Centro",
        "timezone_name": "America/Sao_Paulo",
    }
    values.update(overrides)
    return Unit.infrastructure_objects.create(clinic_id=clinic.pk, **values)


def _room(clinic: Clinic, unit: Unit, **overrides: Any) -> Room:
    values: dict[str, Any] = {"name": "Sala 1"}
    values.update(overrides)
    return Room.infrastructure_objects.create(
        clinic_id=clinic.pk, unit_id=unit.pk, **values
    )


def _pattern(
    clinic: Clinic,
    professional: User,
    unit: Unit,
    *,
    weekday: int,
    start: time,
    end: time,
) -> AvailabilityPattern:
    return AvailabilityPattern.infrastructure_objects.create(
        clinic_id=clinic.pk,
        professional_id=professional.pk,
        unit_id=unit.pk,
        weekday=weekday,
        start_time=start,
        end_time=end,
        valid_from=date(2020, 1, 1),
    )


def _aware(day: date, hour: int, minute: int = 0, tz: ZoneInfo = SP_TZ) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _request_kwargs(
    clinic: Clinic,
    patient: User,
    therapist: User,
    unit: Unit,
    service: Service,
    day: date,
    hour: int,
) -> dict[str, Any]:
    return {
        "clinic_id": clinic.pk,
        "actor": patient,
        "service_id": service.pk,
        "professional_id": therapist.pk,
        "unit_id": unit.pk,
        "start_at": _aware(day, hour),
        "end_at": _aware(day, hour) + timedelta(minutes=service.duration_minutes),
        "idempotency_key": str(uuid4()),
        "request_id": uuid4(),
    }


# ---------------------------------------------------------------------------
# 8.8.1 Availability and slot generation
# ---------------------------------------------------------------------------


def test_free_slots_generated_from_recurring_pattern() -> None:
    """8.8.1.2: Slots follow duration + buffer inside one availability window."""
    clinic = ClinicFactory.create()
    _admin, _patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)  # 50min + 10min buffer
    target = date(2026, 9, 7)
    _pattern(
        clinic,
        therapist,
        unit,
        weekday=target.weekday(),
        start=time(9, 0),
        end=time(11, 0),
    )

    slots = scheduling_services.free_slots(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        from_date=target,
        to_date=target,
    )

    assert [slot.astimezone(SP_TZ).strftime("%H:%M") for slot in slots] == [
        "09:00",
        "10:00",
    ]


def test_override_removes_availability_for_one_day() -> None:
    """8.8.1.1: A date override marked unavailable blocks the whole day."""
    clinic = ClinicFactory.create()
    _admin, _patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)
    target = date(2026, 9, 7)
    _pattern(
        clinic,
        therapist,
        unit,
        weekday=target.weekday(),
        start=time(9, 0),
        end=time(11, 0),
    )
    AvailabilityOverride.infrastructure_objects.create(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        date=target,
        available=False,
        reason="Feriado",
    )

    slots = scheduling_services.free_slots(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        from_date=target,
        to_date=target,
    )
    assert slots == []


def test_schedule_block_removes_overlapping_slot() -> None:
    """8.8.1.1: A blocking window removes slots it overlaps."""
    clinic = ClinicFactory.create()
    _admin, _patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)
    target = date(2026, 9, 7)
    _pattern(
        clinic,
        therapist,
        unit,
        weekday=target.weekday(),
        start=time(9, 0),
        end=time(11, 0),
    )
    ScheduleBlock.infrastructure_objects.create(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        start_at=_aware(target, 9, 0),
        end_at=_aware(target, 9, 50),
        reason="Reunião",
    )

    slots = scheduling_services.free_slots(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        from_date=target,
        to_date=target,
    )
    assert [slot.astimezone(SP_TZ).strftime("%H:%M") for slot in slots] == ["10:00"]


def test_free_slots_skips_hour_on_dst_spring_forward() -> None:
    """8.8.1.4: A spring-forward day never yields the nonexistent 02:00 slot."""
    clinic = ClinicFactory.create()
    _admin, _patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic, timezone_name="America/New_York")
    service = _service(clinic, duration_minutes=60, buffer_minutes=0)
    target = date(2026, 3, 8)  # US spring-forward day (clocks jump 02:00 -> 03:00)
    _pattern(
        clinic,
        therapist,
        unit,
        weekday=target.weekday(),
        start=time(0, 0),
        end=time(23, 59),
    )

    slots = scheduling_services.free_slots(
        clinic_id=clinic.pk,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        from_date=target,
        to_date=target,
    )

    # A 00:00-23:59 window on a 23-hour day holds 22 hourly slots, and the
    # nonexistent 02:00 local time is skipped rather than produced.
    local_times = [
        slot.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M")
        for slot in slots
    ]
    assert len(slots) == 22
    assert "02:00" not in local_times
    assert "01:00" in local_times
    assert "03:00" in local_times


# ---------------------------------------------------------------------------
# 8.8.2 Appointment state machine
# ---------------------------------------------------------------------------


def test_patient_requests_appointment_idempotently() -> None:
    """8.8.2.2: A request reserves the slot and is idempotent by key."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)
    kwargs = _request_kwargs(
        clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
    )

    first = scheduling_services.request_appointment(**kwargs)
    second = scheduling_services.request_appointment(**kwargs)

    assert first.pk == second.pk
    assert first.status == AppointmentStatus.REQUESTED


def test_request_rejects_overlapping_slot() -> None:
    """8.8.1.4: Two concurrent reservations of the same slot are blocked."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)
    kwargs = _request_kwargs(
        clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
    )
    scheduling_services.request_appointment(**kwargs)

    with pytest.raises(ValidationError, match="horário"):
        scheduling_services.request_appointment(
            **{**kwargs, "idempotency_key": str(uuid4())}
        )


def test_confirm_then_complete_and_no_show_transitions() -> None:
    """8.8.2.1: Authorized staff confirm, complete and record no-show."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )

    confirmed = scheduling_services.confirm_appointment(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )
    assert confirmed.status == AppointmentStatus.CONFIRMED

    completed = scheduling_services.complete_appointment(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )
    assert completed.status == AppointmentStatus.COMPLETED
    assert completed.attendance_recorded_by_id == therapist.pk

    # A completed appointment is terminal.
    with pytest.raises(ValidationError):
        scheduling_services.confirm_appointment(
            clinic_id=clinic.pk,
            actor=therapist,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


def test_reschedule_preserves_history_and_releases_old_slot() -> None:
    """8.8.2.3: Rescheduling re-validates and records from/to in history."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    scheduling_services.confirm_appointment(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    new_start = _aware(date(2026, 9, 8), 10)
    new_end = new_start + timedelta(minutes=service.duration_minutes)
    rescheduled = scheduling_services.request_reschedule(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        start_at=new_start,
        end_at=new_end,
        request_id=uuid4(),
    )
    assert rescheduled.status == AppointmentStatus.RESCHEDULE_REQUESTED

    # Old slot released: a new request at the original time now succeeds.
    scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )

    events = list(
        AppointmentEvent.infrastructure_objects.filter(appointment=appointment)
    )
    kinds = {event.kind for event in events}
    assert AppointmentEvent.Kind.RESCHEDULE_REQUESTED in kinds
    reschedule_event = next(
        e for e in events if e.kind == AppointmentEvent.Kind.RESCHEDULE_REQUESTED
    )
    assert reschedule_event.detail["to_start"] == new_start.isoformat()


def test_cancel_releases_slot_and_records_reason() -> None:
    """8.8.2.3: Cancellation preserves history and frees the slot."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    canceled = scheduling_services.cancel_appointment(
        clinic_id=clinic.pk,
        actor=patient,
        appointment_id=appointment.pk,
        reason="Precisei remarcar",
        request_id=uuid4(),
    )
    assert canceled.status == AppointmentStatus.CANCELED
    assert canceled.cancel_reason == "Precisei remarcar"

    # Slot is free again.
    scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )


def test_unlinked_therapist_cannot_confirm() -> None:
    """8.8.2.4: A therapist without an active link cannot manage the appointment."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )

    with pytest.raises(PermissionDenied):
        scheduling_services.confirm_appointment(
            clinic_id=clinic.pk,
            actor=therapist,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


def test_cross_clinic_appointment_denied() -> None:
    """8.8.2.4: Appointments from another clinic are never reachable."""
    clinic_a = ClinicFactory.create()
    _admin_a, patient_a, _profile_a = _linked_patient(clinic_a)
    therapist_a = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic_a, user=therapist_a, role=ClinicMembership.Role.THERAPIST
    )
    unit_a = _unit(clinic_a)
    service_a = _service(clinic_a)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic_a, patient_a, therapist_a, unit_a, service_a, date(2026, 9, 7), 9
        )
    )

    clinic_b = ClinicFactory.create()
    _admin_b, _patient_b, _profile_b = _linked_patient(clinic_b, email="b@example.test")

    with pytest.raises(PermissionDenied):
        scheduling_services.confirm_appointment(
            clinic_id=clinic_b.pk,
            actor=_admin_b,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.8.3 Reminders
# ---------------------------------------------------------------------------


def test_upsert_reminder_preference() -> None:
    """8.8.3.1: A patient manages their own reminder preferences."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    preference = upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=True,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )
    assert preference.enabled is True
    assert preference.advance_minutes == 120

    # Idempotent upsert.
    updated = upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=False,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )
    assert updated.pk == preference.pk
    assert updated.enabled is False


def test_schedule_and_cancel_appointment_reminder() -> None:
    """8.8.3.2: Reminders are idempotent and canceled on state change."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=True,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )

    key = f"rem:{uuid4()}"
    reminder = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert reminder is not None
    assert reminder.scheduled_for == appointment.start_at - timedelta(minutes=120)

    # Idempotent.
    again = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert again is not None
    assert again.pk == reminder.pk

    cancelled = cancel_reminders_for_appointment(
        clinic_id=clinic.pk, appointment_id=appointment.pk, request_id=uuid4()
    )
    assert cancelled == 1
    reminder.refresh_from_db()
    assert reminder.status == ReminderStatus.CANCELED


# ---------------------------------------------------------------------------
# 8.8.4 Messaging
# ---------------------------------------------------------------------------


def test_clinical_conversation_requires_active_link() -> None:
    """8.8.4.1: Clinical conversations block participants without an active link."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    _therapist = _link_therapist(clinic, admin, profile)

    # Unlinked therapist cannot join a clinical conversation with the patient.
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(ValidationError, match="vínculo"):
        create_conversation(
            clinic_id=clinic.pk,
            actor=patient,
            kind=ConversationKind.CLINICAL,
            subject="Acompanhamento",
            participant_ids=[outsider.pk],
            request_id=uuid4(),
        )


def test_conversation_message_flow_and_read_receipts() -> None:
    """8.8.4.2/8.8.4.4: Messages are immutable; read receipts are idempotent."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)

    conversation = create_conversation(
        clinic_id=clinic.pk,
        actor=patient,
        kind=ConversationKind.CLINICAL,
        subject="Acompanhamento",
        participant_ids=[therapist.pk],
        request_id=uuid4(),
    )
    message = send_message(
        clinic_id=clinic.pk,
        actor=patient,
        conversation_id=conversation.pk,
        body="Como estou me sentindo esta semana",
        request_id=uuid4(),
    )
    assert message.body == "Como estou me sentindo esta semana"

    # Therapist can read; patient cannot create duplicate receipts for same messages.
    first = mark_conversation_read(
        clinic_id=clinic.pk, actor=therapist, conversation_id=conversation.pk
    )
    assert first == 1
    second = mark_conversation_read(
        clinic_id=clinic.pk, actor=therapist, conversation_id=conversation.pk
    )
    assert second == 0


def test_non_participant_cannot_send_message() -> None:
    """8.8.4.4: A user outside the conversation cannot send or read."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    conversation = create_conversation(
        clinic_id=clinic.pk,
        actor=patient,
        kind=ConversationKind.CLINICAL,
        subject="Acompanhamento",
        participant_ids=[therapist.pk],
        request_id=uuid4(),
    )

    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        send_message(
            clinic_id=clinic.pk,
            actor=outsider,
            conversation_id=conversation.pk,
            body="Intruso",
            request_id=uuid4(),
        )


def test_attachment_rejects_unsafe_file_and_quarantines() -> None:
    """8.8.5.1/8.8.5.2: Attachments validate type and stay quarantined."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    conversation = create_conversation(
        clinic_id=clinic.pk,
        actor=patient,
        kind=ConversationKind.CLINICAL,
        subject="Acompanhamento",
        participant_ids=[therapist.pk],
        request_id=uuid4(),
    )
    message = send_message(
        clinic_id=clinic.pk,
        actor=patient,
        conversation_id=conversation.pk,
        body="Segue documento",
        request_id=uuid4(),
    )

    unsafe = SimpleUploadedFile(
        "malware.exe", b"MZ\x00\x01", content_type="application/x-msdownload"
    )
    with pytest.raises(ValidationError):
        add_attachment(
            clinic_id=clinic.pk,
            actor=patient,
            message_id=message.pk,
            upload=unsafe,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# HTTP smoke tests (8.8.2/8.8.4 over the wire)
# ---------------------------------------------------------------------------


def _force_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def test_appointment_request_http_flow(client: Client) -> None:
    """8.8.2: Patient requests a consultation over HTTP and sees the agenda."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    _force_client(client, clinic, patient)

    get_res = client.get(reverse("appointment_request"))
    assert get_res.status_code == 200
    assert "Solicitar consulta" in get_res.content.decode()

    post_res = client.post(
        reverse("appointment_request"),
        data={
            "service": str(service.pk),
            "professional": str(therapist.pk),
            "unit": str(unit.pk),
            "start_at": "2026-09-07T09:00",
        },
    )
    assert post_res.status_code == 302

    appointment = Appointment.infrastructure_objects.get(
        clinic_id=clinic.pk, patient_profile__user_id=patient.pk
    )
    assert appointment.status == AppointmentStatus.REQUESTED

    list_res = client.get(reverse("appointment_list"))
    assert list_res.status_code == 200
    assert "Agenda" in list_res.content.decode()
    assert "Sessão individual" in list_res.content.decode()


# ---------------------------------------------------------------------------
# 8.8.1.3 Weekly calendar
# ---------------------------------------------------------------------------


def test_weekly_calendar_renders_grid_and_textual_list(client: Client) -> None:
    """8.8.1.3: The weekly grid has an equivalent textual list and shows slots."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    _force_client(client, clinic, patient)

    res = client.get(reverse("appointment_calendar") + "?date=2026-09-07")
    content = res.content.decode()
    assert res.status_code == 200
    assert "Agenda semanal" in content
    assert "Lista textual equivalente" in content
    assert "Sessão individual" in content


# ---------------------------------------------------------------------------
# 8.8.3.3 Neutral delivery templates
# ---------------------------------------------------------------------------


def test_neutral_delivery_templates_contain_no_clinical_content() -> None:
    """8.8.3.3: Reminder and message templates expose no clinical payload."""
    reminder_text = appointment_reminder_message(
        service_name="Sessão individual",
        start_at=datetime(2026, 9, 7, 9, 0, tzinfo=SP_TZ),
        tz_name="America/Sao_Paulo",
    )
    assert "Sessão individual" in reminder_text
    assert "09:00" in reminder_text
    for forbidden in ("humor", "ansiedade", "tristeza", "diário", "resposta"):
        assert forbidden not in reminder_text.lower()

    message_text = new_message_notification_message(sender_name="Dra. Ana")
    assert "Dra. Ana" in message_text
    assert "nova mensagem" in message_text.lower()


# ---------------------------------------------------------------------------
# 8.8.3.4 Reminder edge cases
# ---------------------------------------------------------------------------


def test_snooze_reminder_delays_pending_reminder() -> None:
    """8.8.3.4: A patient can snooze their own pending reminder."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=True,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )
    reminder = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=f"rem:{uuid4()}",
        request_id=uuid4(),
    )
    assert reminder is not None
    original = reminder.scheduled_for

    snoozed = snooze_reminder(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_id=reminder.pk,
        minutes=30,
        request_id=uuid4(),
    )
    assert snoozed.scheduled_for == original + timedelta(minutes=30)


def test_failed_channel_marks_reminder_failed() -> None:
    """8.8.3.4: An unavailable channel marks the reminder as failed."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=True,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )
    reminder = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=f"rem:{uuid4()}",
        request_id=uuid4(),
    )
    assert reminder is not None

    failed = mark_reminder_failed(clinic_id=clinic.pk, reminder_id=reminder.pk)
    assert failed.status == ReminderStatus.FAILED


def test_consent_withdrawal_blocks_new_reminders() -> None:
    """8.8.3.4: Disabling the preference prevents new reminders."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=False,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )

    reminder = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=f"rem:{uuid4()}",
        request_id=uuid4(),
    )
    assert reminder is None


def test_timezone_renders_same_instant_in_local_time() -> None:
    """8.8.3.4: A reminder instant renders in the patient's own timezone."""
    instant = datetime(2026, 9, 7, 12, 0, tzinfo=ZoneInfo("UTC"))
    sao_paulo = appointment_reminder_message(
        service_name="Sessão", start_at=instant, tz_name="America/Sao_Paulo"
    )
    new_york = appointment_reminder_message(
        service_name="Sessão", start_at=instant, tz_name="America/New_York"
    )
    assert "09:00" in sao_paulo  # UTC 12:00 -> São Paulo 09:00
    assert "08:00" in new_york  # UTC 12:00 -> Nova York 08:00 (EDT)


def test_low_energy_suppresses_non_essential_only() -> None:
    """8.8.3.4: Low-energy mode blocks check-in reminders but not appointments."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    LowEnergyMode.infrastructure_objects.create(
        clinic_id=clinic.pk,
        patient_profile_id=profile.pk,
        author_id=patient.pk,
        started_at=dj_timezone.now() - timedelta(hours=1),
        ends_at=dj_timezone.now() + timedelta(hours=1),
        suppress_non_essential_notifications=True,
    )

    # Non-essential check-in reminder is suppressed.
    suppressed = schedule_reminder(
        clinic_id=clinic.pk,
        actor=patient,
        patient_profile_id=profile.pk,
        reminder_type=ReminderType.CHECKIN,
        channel="push",
        scheduled_for=dj_timezone.now() + timedelta(hours=2),
        idempotency_key=f"rem:{uuid4()}",
        request_id=uuid4(),
        is_essential=False,
    )
    assert suppressed is None

    # Essential appointment reminder is still scheduled.
    unit = _unit(clinic)
    service = _service(clinic)
    appointment = scheduling_services.request_appointment(
        **_request_kwargs(
            clinic, patient, therapist, unit, service, date(2026, 9, 7), 9
        )
    )
    upsert_reminder_preference(
        clinic_id=clinic.pk,
        actor=patient,
        reminder_type=ReminderType.APPOINTMENT,
        channel="push",
        enabled=True,
        advance_minutes=120,
        silence_start=None,
        silence_end=None,
        timezone_name="America/Sao_Paulo",
        max_daily=3,
    )
    essential = schedule_appointment_reminder(
        clinic_id=clinic.pk,
        actor=therapist,
        appointment_id=appointment.pk,
        idempotency_key=f"rem:{uuid4()}",
        request_id=uuid4(),
    )
    assert essential is not None


# ---------------------------------------------------------------------------
# 8.8.4.2 Pagination and 8.8.4.4 out-of-hours response
# ---------------------------------------------------------------------------


def test_message_history_paginates(client: Client) -> None:
    """8.8.4.2: The conversation history paginates server-side."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    conversation = create_conversation(
        clinic_id=clinic.pk,
        actor=patient,
        kind=ConversationKind.CLINICAL,
        subject="Histórico",
        participant_ids=[therapist.pk],
        request_id=uuid4(),
    )
    for index in range(55):
        send_message(
            clinic_id=clinic.pk,
            actor=patient,
            conversation_id=conversation.pk,
            body=f"mensagem-{index:02d}",
            request_id=uuid4(),
        )
    _force_client(client, clinic, patient)

    first_page = client.get(reverse("conversation_detail", args=[conversation.pk]))
    assert first_page.status_code == 200
    assert "Mais recentes ›" in first_page.content.decode()
    assert "mensagem-00" in first_page.content.decode()
    assert "mensagem-54" not in first_page.content.decode()

    second_page = client.get(
        reverse("conversation_detail", args=[conversation.pk]) + "?page=2"
    )
    assert second_page.status_code == 200
    assert "‹ Mais antigas" in second_page.content.decode()
    assert "mensagem-54" in second_page.content.decode()


def test_out_of_hours_response_helper() -> None:
    """8.8.4.4: The configured response only appears outside operating hours."""
    weekly_hours = {"monday": [{"start": "09:00", "end": "17:00"}]}
    inside = datetime(2026, 9, 7, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    outside = datetime(2026, 9, 7, 20, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

    assert within_operating_hours(
        weekly_hours=weekly_hours, now=inside, tz_name="America/Sao_Paulo"
    )
    assert not within_operating_hours(
        weekly_hours=weekly_hours, now=outside, tz_name="America/Sao_Paulo"
    )
    assert (
        out_of_hours_response(
            weekly_hours=weekly_hours,
            now=inside,
            tz_name="America/Sao_Paulo",
            instructions="",
        )
        is None
    )
    response = out_of_hours_response(
        weekly_hours=weekly_hours,
        now=outside,
        tz_name="America/Sao_Paulo",
        instructions="Respondemos em horário comercial.",
    )
    assert response == "Respondemos em horário comercial."


# ---------------------------------------------------------------------------
# 8.8.5.2 / 8.8.5.4 Attachments: download, audit and delete
# ---------------------------------------------------------------------------


def _conversation_and_message(
    clinic: Clinic, patient: User, therapist: User
) -> tuple[Conversation, Message]:
    conversation = create_conversation(
        clinic_id=clinic.pk,
        actor=patient,
        kind=ConversationKind.CLINICAL,
        subject="Anexos",
        participant_ids=[therapist.pk],
        request_id=uuid4(),
    )
    message = send_message(
        clinic_id=clinic.pk,
        actor=patient,
        conversation_id=conversation.pk,
        body="Segue anexo",
        request_id=uuid4(),
    )
    return conversation, message


def test_attachment_download_requires_clean_scan_and_participant() -> None:
    """8.8.5.2/8.8.5.4: Only clean attachments reach authorized participants."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    _conversation, message = _conversation_and_message(clinic, patient, therapist)

    attachment = MessageAttachment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        message_id=message.pk,
        uploader_id=patient.pk,
        original_name="documento.pdf",
        content_type="application/pdf",
        size_bytes=128,
        scan_status=ScanStatus.QUARANTINED,
    )

    # Quarantined attachment is never downloadable.
    with pytest.raises(PermissionDenied):
        download_attachment(
            clinic_id=clinic.pk,
            actor=therapist,
            attachment_id=attachment.pk,
            request_id=uuid4(),
        )

    attachment.scan_status = ScanStatus.CLEAN
    attachment.save(update_fields=("scan_status", "updated_at"))

    # A non-participant cannot download even a clean attachment.
    with pytest.raises(PermissionDenied):
        download_attachment(
            clinic_id=clinic.pk,
            actor=outsider,
            attachment_id=attachment.pk,
            request_id=uuid4(),
        )

    # An authorized participant can.
    result = download_attachment(
        clinic_id=clinic.pk,
        actor=therapist,
        attachment_id=attachment.pk,
        request_id=uuid4(),
    )
    assert result.pk == attachment.pk


def test_attachment_delete_is_restricted_and_audited() -> None:
    """8.8.5.4: Only the uploader/admin can delete, and the action is audited."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    _conversation, message = _conversation_and_message(clinic, patient, therapist)

    attachment = MessageAttachment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        message_id=message.pk,
        uploader_id=patient.pk,
        original_name="documento.pdf",
        content_type="application/pdf",
        size_bytes=128,
        scan_status=ScanStatus.CLEAN,
    )

    # A therapist who did not upload the file cannot delete it.
    with pytest.raises(PermissionDenied):
        delete_attachment(
            clinic_id=clinic.pk,
            actor=therapist,
            attachment_id=attachment.pk,
            request_id=uuid4(),
        )

    # The uploader (patient) can delete, and the action is audited.
    delete_attachment(
        clinic_id=clinic.pk,
        actor=patient,
        attachment_id=attachment.pk,
        request_id=uuid4(),
    )
    assert not MessageAttachment.infrastructure_objects.filter(
        pk=attachment.pk
    ).exists()
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        resource_type="message_attachment",
        resource_id=str(attachment.pk),
        action="delete",
    ).exists()
