"""Tests for clinical video conferencing and telemetry (8.13.4)."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from integrations.contracts import FakeVideoAdapter
from integrations.models import (
    VideoParticipantRole,
    VideoSessionStatus,
)
from integrations.video import (
    admit_participant_from_waiting_room,
    close_video_session,
    configure_session_recording,
    create_clinical_video_session,
    enter_waiting_room,
    generate_participant_access_token,
    mark_device_check_completed,
    record_quality_telemetry,
    validate_room_entry,
)
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
    return ClinicFactory.create(name="Clínica Vídeo Teste")


@pytest.fixture
def therapist_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="terapeuta.video@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.video@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def test_appointment(
    test_clinic: Clinic, therapist_user: User, patient_user: User
) -> Appointment:
    profile = PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Teleconsulta",
        birth_date=date(1988, 3, 25),
    )
    unit = Unit.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Unidade Teleatendimento",
    )
    service = Service.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Teleconsulta Psicológica",
        duration_minutes=50,
        is_active=True,
    )
    start = timezone.now() + timedelta(minutes=30)
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
def test_clinical_video_session_and_ephemeral_token_lifecycle(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user: User
) -> None:
    """Clinical video session creates unique tokens and enforces entry windows."""
    adapter = FakeVideoAdapter()
    session = create_clinical_video_session(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        adapter=adapter,
    )
    assert session.room_id.startswith("room_")
    assert session.status == VideoSessionStatus.PENDING

    # Token issuance
    token = generate_participant_access_token(
        session_id=session.id,
        user_id=therapist_user.id,
        role=VideoParticipantRole.THERAPIST,
        valid_duration_minutes=300,
    )
    assert token.token != ""
    assert token.role == VideoParticipantRole.THERAPIST

    # Window validation
    # 1. Too early: 20 minutes before start (grace is 10 min)
    early_time = test_appointment.start_at - timedelta(minutes=20)
    with pytest.raises(ValidationError, match="A sala ainda não está liberada"):
        validate_room_entry(token_str=token.token, now=early_time)

    # 2. On time: 5 minutes before start
    valid_time = test_appointment.start_at - timedelta(minutes=5)
    validated = validate_room_entry(token_str=token.token, now=valid_time)
    assert validated.id == token.id

    # 3. Too late: 45 minutes after end (grace is 30 min)
    late_time = test_appointment.end_at + timedelta(minutes=45)
    with pytest.raises(ValidationError, match="atendimento desta sala foi encerrado"):
        validate_room_entry(token_str=token.token, now=late_time)


@pytest.mark.django_db
def test_bilateral_recording_consent_controls(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user: User
) -> None:
    """Recording is blocked by default and requires explicit bilateral consent."""
    session = create_clinical_video_session(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
    )
    assert session.is_recording_enabled is False

    # Only therapist consented -> BLOCKED
    session = configure_session_recording(
        session_id=session.id,
        therapist_consented=True,
        patient_consented=False,
        actor_id=therapist_user.id,
    )
    assert session.is_recording_enabled is False

    # Both consented -> ENABLED
    session = configure_session_recording(
        session_id=session.id,
        therapist_consented=True,
        patient_consented=True,
        actor_id=therapist_user.id,
    )
    assert session.is_recording_enabled is True


@pytest.mark.django_db
def test_waiting_room_device_checks_and_admission(
    test_clinic: Clinic,
    test_appointment: Appointment,
    therapist_user: User,
    patient_user: User,
) -> None:
    """Participants pass device check before waiting room, and therapist admits."""
    session = create_clinical_video_session(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
    )
    token = generate_participant_access_token(
        session_id=session.id,
        user_id=patient_user.id,
        role=VideoParticipantRole.PATIENT,
    )

    # Cannot enter waiting room without pre-flight check
    with pytest.raises(ValidationError, match="concluir o teste de dispositivos"):
        enter_waiting_room(token_str=token.token)

    # Perform device check and enter waiting room
    mark_device_check_completed(token_str=token.token)
    token = enter_waiting_room(token_str=token.token)
    assert token.in_waiting_room is True

    session.refresh_from_db()
    assert session.status == VideoSessionStatus.WAITING_ROOM

    # Therapist admits patient
    admitted = admit_participant_from_waiting_room(
        session_id=session.id,
        token_str=token.token,
        therapist_actor_id=therapist_user.id,
    )
    assert admitted.in_waiting_room is False
    assert admitted.admitted_at is not None

    session.refresh_from_db()
    assert session.status == VideoSessionStatus.IN_PROGRESS


@pytest.mark.django_db
def test_quality_telemetry_degradation_and_session_closing(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user: User
) -> None:
    """Network degradation triggers contingency; closing logs duration."""
    adapter = FakeVideoAdapter()
    session = create_clinical_video_session(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        adapter=adapter,
    )

    # 1. Normal telemetry
    tel_ok = record_quality_telemetry(
        session_id=session.id,
        packet_loss_percent=1.0,
        jitter_ms=15.0,
        latency_ms=80.0,
    )
    assert tel_ok.degradation_detected is False

    # 2. Degraded telemetry (packet loss > 5%)
    tel_bad = record_quality_telemetry(
        session_id=session.id,
        packet_loss_percent=8.5,
        jitter_ms=120.0,
        latency_ms=450.0,
    )
    assert tel_bad.degradation_detected is True
    assert tel_bad.contingency_activated is True

    # 3. Close session
    closed_session = close_video_session(
        session_id=session.id,
        actor_id=therapist_user.id,
        adapter=adapter,
    )
    assert closed_session.status == VideoSessionStatus.COMPLETED
    assert closed_session.closed_at is not None
    assert adapter.rooms[closed_session.room_id].status == "closed"
