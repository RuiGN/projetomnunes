"""Tests for appointment saga and circuit breaker (8.13.5)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Never
from uuid import uuid4

import pytest
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from integrations.contracts import (
    FakeCalendarAdapter,
    FakeVideoAdapter,
    FakeWhatsAppAdapter,
)
from integrations.models import ExternalCalendarMapping, VideoSession
from integrations.sagas import (
    SagaStatus,
    circuit_breaker,
    execute_appointment_saga,
    get_integration_operations_dashboard,
    reconcile_appointment_integrations,
)
from integrations.whatsapp import create_whatsapp_template, record_whatsapp_consent
from people.models import PatientProfile
from scheduling.models import Appointment, AppointmentStatus, Service, Unit
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Sagas Teste")


@pytest.fixture
def therapist_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="terapeuta.saga@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.saga@test.org")
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
        full_name="Paciente Saga",
        birth_date=date(1991, 7, 14),
    )
    unit = Unit.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Unidade Sagas",
    )
    service = Service.infrastructure_objects.create(
        clinic_id=test_clinic.id,
        name="Consulta Psicoterapêutica",
        duration_minutes=50,
        is_active=True,
    )
    start = timezone.now() + timedelta(days=1)
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
def test_appointment_saga_full_journey_success(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user: User
) -> None:
    """End-to-end saga succeeds across calendar, video room and WhatsApp reminder."""
    phone = "+5581988887777"
    record_whatsapp_consent(
        clinic_id=test_clinic.id,
        phone_number=phone,
    )
    create_whatsapp_template(
        clinic_id=test_clinic.id,
        name="lembrete_saga",
        body_template="Olá {nome}, seu horário está confirmado para {data}.",
    )

    cal_adapter = FakeCalendarAdapter()
    vid_adapter = FakeVideoAdapter()
    msg_adapter = FakeWhatsAppAdapter()

    saga = execute_appointment_saga(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        calendar_provider="google_calendar",
        send_whatsapp_notification=True,
        whatsapp_recipient_phone=phone,
        whatsapp_template_name="lembrete_saga",
        whatsapp_params={"nome": "Paciente", "data": "Amanhã"},
        calendar_adapter=cal_adapter,
        video_adapter=vid_adapter,
        messaging_adapter=msg_adapter,
        actor_id=therapist_user.id,
    )

    assert saga.status == SagaStatus.COMPLETED
    assert "calendar_sync" in saga.steps_completed
    assert "video_provisioning" in saga.steps_completed
    assert "whatsapp_notification" in saga.steps_completed

    # Check persistence across all submodules
    mapping = (
        ExternalCalendarMapping.objects.for_clinic(test_clinic.id)
        .filter(appointment_id=test_appointment.id)
        .first()
    )
    assert mapping is not None
    assert mapping.sync_status == "synced"

    session = (
        VideoSession.objects.for_clinic(test_clinic.id)
        .filter(appointment_id=test_appointment.id)
        .first()
    )
    assert session is not None


@pytest.mark.django_db
def test_appointment_saga_transactional_compensation(
    test_clinic: Clinic, test_appointment: Appointment
) -> None:
    """Failure during video provisioning compensates synced calendar event."""
    cal_adapter = FakeCalendarAdapter()

    class FailingVideoAdapter(FakeVideoAdapter):
        def create_room(self, **kwargs: object) -> Never:
            raise ConnectionError("Video provider timeout")

    saga = execute_appointment_saga(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        calendar_provider="google_calendar",
        send_whatsapp_notification=False,
        calendar_adapter=cal_adapter,
        video_adapter=FailingVideoAdapter(),
    )

    assert saga.status == SagaStatus.COMPENSATED
    assert "calendar_sync_reverted" in saga.compensation_log
    assert "Video provider timeout" in saga.last_error

    # Calendar event was rolled back
    mapping = (
        ExternalCalendarMapping.objects.for_clinic(test_clinic.id)
        .filter(appointment_id=test_appointment.id)
        .first()
    )
    assert mapping is not None
    assert mapping.sync_status == "canceled"


@pytest.mark.django_db
def test_circuit_breaker_trips_to_fallback(
    test_clinic: Clinic, test_appointment: Appointment
) -> None:
    """Degraded provider opens circuit breaker; saga applies fallback."""
    provider = "google_calendar"
    circuit_breaker.set_simulation(provider, should_fail=True)
    assert circuit_breaker.is_open(provider) is True

    saga = execute_appointment_saga(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        calendar_provider=provider,
        send_whatsapp_notification=False,
        video_adapter=FakeVideoAdapter(),
    )

    assert saga.status == SagaStatus.COMPLETED_WITH_FALLBACK
    assert "calendar_sync" not in saga.steps_completed
    assert "video_provisioning" in saga.steps_completed
    assert "tripped" in saga.last_error

    # Clean up circuit breaker simulation
    circuit_breaker.set_simulation(provider, should_fail=False)
    circuit_breaker.record_success(provider)


@pytest.mark.django_db
def test_operational_dashboard_and_reconciliation(
    test_clinic: Clinic, test_appointment: Appointment, therapist_user: User
) -> None:
    """Dashboard returns provider status; reconciliation fixes missing records."""
    dashboard = get_integration_operations_dashboard(clinic_id=test_clinic.id)
    assert "providers" in dashboard
    assert dashboard["providers"]["whatsapp"]["status"] == "healthy"
    assert "sagas" in dashboard

    # Reconcile missing integrations
    cal_adapter = FakeCalendarAdapter()
    vid_adapter = FakeVideoAdapter()

    res = reconcile_appointment_integrations(
        clinic_id=test_clinic.id,
        appointment_id=test_appointment.id,
        actor_id=therapist_user.id,
        calendar_adapter=cal_adapter,
        video_adapter=vid_adapter,
    )

    assert res["calendar_status"] == "synced"
    assert res["video_room_id"] != ""
