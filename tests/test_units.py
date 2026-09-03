"""Acceptance tests for PRD 8.10.1 — cadastro de clínica, unidades e salas."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from scheduling.models import Appointment, AppointmentStatus, Room, Service, Unit
from scheduling.unit_services import (
    create_room,
    create_unit,
    deactivate_room,
    deactivate_unit,
    update_unit,
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


def _appointment(clinic: Clinic, unit: Unit, professional: User) -> Appointment:
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente",
        birth_date=date(1990, 1, 1),
        email="p@example.test",
    )
    start = timezone.now() + timedelta(days=1)
    return Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=_service(clinic).pk,
        professional_id=professional.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status=AppointmentStatus.CONFIRMED,
        idempotency_key=uuid4().hex,
        requested_by_id=professional.pk,
    )


# ---------------------------------------------------------------------------
# 8.10.1.1 / 8.10.1.2 — unit and room modeling with tenant isolation
# ---------------------------------------------------------------------------


def test_create_unit_requires_admin() -> None:
    clinic, _admin, staff = _admin_and_staff()
    with pytest.raises(PermissionDenied):
        create_unit(
            clinic_id=clinic.pk,
            actor=staff,
            name="Unidade Sul",
            address={},
            timezone_name="America/Sao_Paulo",
            request_id=uuid4(),
        )


def test_create_unit_rejects_duplicate_name() -> None:
    clinic, admin, _staff = _admin_and_staff()
    create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        create_unit(
            clinic_id=clinic.pk,
            actor=admin,
            name="Unidade Centro",
            address={},
            timezone_name="America/Sao_Paulo",
            request_id=uuid4(),
        )


def test_create_unit_audits() -> None:
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(action="create", resource_type="unit", resource_id=str(unit.pk))
        .exists()
    )


def test_update_unit_changes_timezone() -> None:
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    updated = update_unit(
        clinic_id=clinic.pk,
        actor=admin,
        unit_id=unit.pk,
        name="Unidade Centro",
        address={},
        timezone_name="America/Recife",
        request_id=uuid4(),
    )
    assert updated.timezone_name == "America/Recife"


def test_deactivate_unit_blocks_future_appointments() -> None:
    """8.10.1.3: deactivation is blocked when future appointments are linked."""
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    _appointment(clinic, unit, admin)

    with pytest.raises(ValidationError):
        deactivate_unit(
            clinic_id=clinic.pk, actor=admin, unit_id=unit.pk, request_id=uuid4()
        )


def test_create_room_and_deactivate() -> None:
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    room = create_room(
        clinic_id=clinic.pk,
        actor=admin,
        unit_id=unit.pk,
        name="Sala 1",
        request_id=uuid4(),
    )
    assert room.name == "Sala 1"
    assert room.is_active is True

    deactivated = deactivate_room(
        clinic_id=clinic.pk, actor=admin, room_id=room.pk, request_id=uuid4()
    )
    assert deactivated.is_active is False


def test_create_room_rejects_duplicate_in_unit() -> None:
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    create_room(
        clinic_id=clinic.pk,
        actor=admin,
        unit_id=unit.pk,
        name="Sala 1",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        create_room(
            clinic_id=clinic.pk,
            actor=admin,
            unit_id=unit.pk,
            name="Sala 1",
            request_id=uuid4(),
        )


def test_unit_cross_clinic_denied() -> None:
    clinic_a, admin_a, _staff_a = _admin_and_staff()
    clinic_b, admin_b, _staff_b = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        name="Unidade A",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        update_unit(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            unit_id=unit.pk,
            name="Unidade A",
            address={},
            timezone_name="America/Sao_Paulo",
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------


def _force_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


def test_unit_list_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    _force_client(client, clinic, admin)
    response = client.get(reverse("unit_list"))
    assert response.status_code == 200
    assert "Unidades e salas" in response.content.decode()


def test_unit_create_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    _force_client(client, clinic, admin)
    response = client.post(
        reverse("unit_create"),
        data={"name": "Unidade Norte", "timezone_name": "America/Sao_Paulo"},
    )
    assert response.status_code == 302
    assert Unit.objects.for_clinic(clinic.pk).filter(name="Unidade Norte").exists()


def test_room_create_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    unit = create_unit(
        clinic_id=clinic.pk,
        actor=admin,
        name="Unidade Centro",
        address={},
        timezone_name="America/Sao_Paulo",
        request_id=uuid4(),
    )
    _force_client(client, clinic, admin)
    response = client.post(
        reverse("room_create"), data={"unit": str(unit.pk), "name": "Sala 2"}
    )
    assert response.status_code == 302
    assert Room.objects.for_clinic(clinic.pk).filter(name="Sala 2").exists()
