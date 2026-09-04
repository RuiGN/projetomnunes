"""Tests for external calendar sync and conflict resolution (8.13.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from clinics.models import Clinic, ClinicMembership
from integrations.calendars import (
    ConflictResolutionStrategy,
    check_calendar_authorization_status,
    generate_oauth_state,
    record_calendar_conflict,
    resolve_calendar_conflict,
    sync_appointment_to_external_calendar,
    validate_oauth_state,
)
from integrations.contracts import FakeCalendarAdapter
from integrations.services import store_credential
from people.models import PatientProfile
from scheduling.models import (
    Appointment,
    AppointmentStatus,
    Service,
    Unit,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Calendário Teste")


@pytest.fixture
def therapist_user(test_clinic: Clinic):
    user = UserFactory.create(email="terapeuta.cal@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.cal@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def test_appointment(test_clinic: Clinic, therapist_user, patient_user) -> Appointment:
    profile = PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Teste Calendário",
        birth_date=date(1992, 5, 20),
    )
    unit = Unit.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Unidade Calendário",
    )
    service = Service.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Consulta Padrão",
        duration_minutes=50,
        is_active=True,
    )
    start = timezone.now() + timedelta(days=2)
    end = start + timedelta(minutes=50)
    return Appointment.infrastructure_objects.create(
        clinic=test_clinic,
        unit=unit,
        service=service,
        professional=therapist_user,
        patient_profile=profile,
        start_at=start,
        end_at=end,
        status=AppointmentStatus.CONFIRMED,
        idempotency_key=str(uuid4()),
        requested_by=therapist_user,
    )


@pytest.mark.django_db
def test_oauth_state_tamper_and_expiry_protection(
    test_clinic: Clinic, therapist_user
) -> None:
    """OAuth state tokens are signed with anti-CSRF nonce and reject tampering."""
    state = generate_oauth_state(
        clinic_id=test_clinic.id,
        user_id=therapist_user.id,
        provider="google_calendar",
    )
    decoded = validate_oauth_state(state)
    assert decoded["clinic_id"] == str(test_clinic.id)
    assert decoded["user_id"] == str(therapist_user.id)
    assert decoded["provider"] == "google_calendar"

    # Tampered state rejected
    with pytest.raises(ValidationError, match="Assinatura do estado OAuth inválida"):
        validate_oauth_state(state[:-5] + "XXXXX")


@pytest.mark.django_db
def test_calendar_authorization_status_and_expiration_warning(
    test_clinic: Clinic, therapist_user
) -> None:
    """Calendar authorization alerts when tokens are expired or near expiry."""
    # 1. No credential
    status = check_calendar_authorization_status(
        clinic_id=test_clinic.id, provider="google_calendar"
    )
    assert status["authorized"] is False

    # 2. Expiring soon (<3 days)
    near_expiry = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    store_credential(
        clinic_id=test_clinic.id,
        actor_id=therapist_user.id,
        provider="google_calendar",
        name="Google Calendar Dr. Silva",
        plaintext_secret="token_abc",
        metadata={"token_expires_at": near_expiry, "calendar_id": "primary"},
    )

    status = check_calendar_authorization_status(
        clinic_id=test_clinic.id, provider="google_calendar"
    )
    assert status["authorized"] is True
    assert status["expiring_soon"] is True
    assert "expira em menos de 3 dias" in status["warning"]


@pytest.mark.django_db
def test_appointment_calendar_sync_lifecycle_and_minimized_data(
    test_clinic: Clinic, test_appointment: Appointment
) -> None:
    """Calendar sync pushes neutral appointment data, handles updates."""
    adapter = FakeCalendarAdapter()

    # 1. Initial Sync
    mapping = sync_appointment_to_external_calendar(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        provider="google_calendar",
        adapter=adapter,
    )
    assert mapping.version == 1
    assert mapping.sync_status == "synced"
    assert mapping.external_event_id != ""

    synced_event = adapter.events[mapping.external_event_id]
    assert "Atendimento Clínico" in synced_event.title
    assert "Não altere diretamente" in synced_event.description
    # Ensure no patient PII or diagnosis leaked
    assert "depressão" not in synced_event.description
    assert test_appointment.patient_profile.full_name not in synced_event.title

    # 2. Rescheduled Update
    test_appointment.start_at += timedelta(hours=1)
    test_appointment.end_at += timedelta(hours=1)
    test_appointment.save()

    updated_mapping = sync_appointment_to_external_calendar(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        provider="google_calendar",
        adapter=adapter,
    )
    assert updated_mapping.version == 2
    assert updated_mapping.sync_status == "synced"
    assert adapter.events[mapping.external_event_id].version == 2

    # 3. Cancellation
    test_appointment.status = AppointmentStatus.CANCELED
    test_appointment.save()

    canceled_mapping = sync_appointment_to_external_calendar(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        provider="google_calendar",
        adapter=adapter,
    )
    assert canceled_mapping.sync_status == "canceled"
    assert mapping.external_event_id in adapter.canceled_events


@pytest.mark.django_db
def test_calendar_conflict_detection_and_resolution(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user
) -> None:
    """Conflicts are logged and resolved deterministically."""
    adapter = FakeCalendarAdapter()
    mapping = sync_appointment_to_external_calendar(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        provider="google_calendar",
        adapter=adapter,
    )

    # Conflict detected
    conflict_mapping = record_calendar_conflict(
        clinic_id=test_clinic.id,
        mapping_id=mapping.id,
        conflict_type="TIME_MISMATCH",
        remote_data={"remote_start": (timezone.now() + timedelta(days=3)).isoformat()},
        actor_id=therapist_user.id,
    )
    assert conflict_mapping.sync_status == "conflict"
    assert conflict_mapping.conflict_details["conflict_type"] == "TIME_MISMATCH"

    # Resolve with PREFER_INTERNAL
    resolved = resolve_calendar_conflict(
        clinic_id=test_clinic.id,
        mapping_id=mapping.id,
        strategy=ConflictResolutionStrategy.PREFER_INTERNAL,
        actor_id=therapist_user.id,
        adapter=adapter,
    )
    assert resolved.sync_status == "synced"
    resolved_strat = resolved.conflict_details["resolved_strategy"]
    assert resolved_strat == ConflictResolutionStrategy.PREFER_INTERNAL
