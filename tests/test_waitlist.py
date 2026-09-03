"""Acceptance tests for PRD 8.10.4 — agenda central e lista de espera."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from scheduling.models import (
    Appointment,
    AppointmentStatus,
    Service,
    Unit,
    WaitlistEntry,
    WaitlistStatus,
)
from scheduling.waitlist_services import (
    add_waitlist_entry,
    cancel_waitlist_entry,
    fill_waitlist_entry,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin_and_staff() -> tuple[Clinic, User, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    staff = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=staff, role=ClinicMembership.Role.ADMINISTRATIVE_STAFF
    )
    return clinic, admin, staff


def _service(clinic: Clinic) -> Service:
    return Service.infrastructure_objects.create(
        clinic_id=clinic.pk,
        name="Sessão individual",
        duration_minutes=50,
        buffer_minutes=10,
    )


def _unit(clinic: Clinic) -> Unit:
    return Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade Centro", timezone_name="America/Sao_Paulo"
    )


def _patient(clinic: Clinic) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente Espera",
        birth_date=date(1990, 1, 1),
        email="espera@example.test",
    )


def _appointment(
    clinic: Clinic, service: Service, unit: Unit, professional: User, status: str
) -> Appointment:
    start = timezone.now() + timedelta(days=1)
    return Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=professional.pk,
        patient_profile_id=_patient(clinic).pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=service.duration_minutes),
        status=status,
        idempotency_key=uuid4().hex,
        requested_by_id=professional.pk,
    )


# ---------------------------------------------------------------------------
# 8.10.4.2 — waitlist entry lifecycle
# ---------------------------------------------------------------------------


def test_add_waitlist_entry_requires_reception_role() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)

    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        add_waitlist_entry(
            clinic_id=clinic.pk,
            actor=outsider,
            patient_profile_id=patient.pk,
            unit_id=unit.pk,
            service_id=service.pk,
            preferred_period="manhã",
            contact_note="",
            request_id=uuid4(),
        )


def test_add_waitlist_entry_records_operational_facts_only() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)

    entry = add_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="manhã",
        contact_note="Prefere contato por telefone",
        request_id=uuid4(),
    )

    assert entry.status == WaitlistStatus.WAITING
    assert entry.preferred_period == "manhã"
    assert entry.contact_note == "Prefere contato por telefone"
    assert entry.requested_by_id == admin.pk


def test_cancel_waitlist_entry() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)
    entry = add_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="",
        contact_note="",
        request_id=uuid4(),
    )

    canceled = cancel_waitlist_entry(
        clinic_id=clinic.pk, actor=admin, entry_id=entry.pk, request_id=uuid4()
    )

    assert canceled.status == WaitlistStatus.CANCELED


def test_fill_waitlist_entry_links_appointment() -> None:
    """8.10.4.3: a canceled slot is filled after human confirmation."""
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)
    entry = add_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="",
        contact_note="",
        request_id=uuid4(),
    )
    appointment = _appointment(
        clinic, service, unit, admin, AppointmentStatus.CONFIRMED
    )

    filled = fill_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        entry_id=entry.pk,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    assert filled.status == WaitlistStatus.FILLED
    assert filled.filled_appointment_id == appointment.pk


def test_fill_waitlist_entry_rejects_duplicate_appointment() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)
    entry_a = add_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="",
        contact_note="",
        request_id=uuid4(),
    )
    entry_b = add_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="",
        contact_note="",
        request_id=uuid4(),
    )
    appointment = _appointment(
        clinic, service, unit, admin, AppointmentStatus.CONFIRMED
    )

    fill_waitlist_entry(
        clinic_id=clinic.pk,
        actor=admin,
        entry_id=entry_a.pk,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        fill_waitlist_entry(
            clinic_id=clinic.pk,
            actor=admin,
            entry_id=entry_b.pk,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


def test_waitlist_cross_clinic_denied() -> None:
    clinic_a, admin_a, _staff_a = _admin_and_staff()
    clinic_b, admin_b, _staff_b = _admin_and_staff()
    service = _service(clinic_a)
    unit = _unit(clinic_a)
    patient = _patient(clinic_a)
    entry = add_waitlist_entry(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        patient_profile_id=patient.pk,
        unit_id=unit.pk,
        service_id=service.pk,
        preferred_period="",
        contact_note="",
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        cancel_waitlist_entry(
            clinic_id=clinic_b.pk, actor=admin_b, entry_id=entry.pk, request_id=uuid4()
        )


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------


def _force_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def test_waitlist_list_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    _force_client(client, clinic, admin)
    response = client.get(reverse("waitlist_list"))
    assert response.status_code == 200
    assert "Lista de espera" in response.content.decode()


def test_waitlist_add_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    patient = _patient(clinic)
    _force_client(client, clinic, admin)
    response = client.post(
        reverse("waitlist_add"),
        data={
            "patient_profile": str(patient.pk),
            "unit": str(unit.pk),
            "service": str(service.pk),
            "preferred_period": "tarde",
            "contact_note": "",
        },
    )
    assert response.status_code == 302
    assert (
        WaitlistEntry.objects.for_clinic(clinic.pk)
        .filter(preferred_period="tarde")
        .exists()
    )
