"""Acceptance tests for PRD 8.10.5 — financeiro básico (preços e contas a receber)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from finance import services as finance_services
from finance.models import Charge, ChargeStatus, ServicePrice
from people.models import PatientProfile
from scheduling.models import Appointment, AppointmentStatus, Service, Unit
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


def _confirmed_appointment(
    clinic: Clinic, service: Service, unit: Unit, professional: User
) -> Appointment:
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente Financeiro",
        birth_date=date(1990, 1, 1),
        email="financeiro@example.test",
    )
    start = timezone.now() + timedelta(days=1)
    return Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=professional.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=service.duration_minutes),
        status=AppointmentStatus.CONFIRMED,
        idempotency_key=uuid4().hex,
        requested_by_id=professional.pk,
    )


def _price(clinic: Clinic, service: Service, amount: str = "150.00") -> ServicePrice:
    return ServicePrice.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        amount=Decimal(amount),
        currency="BRL",
        valid_from=date.today() - timedelta(days=1),
    )


# ---------------------------------------------------------------------------
# 8.10.5.1 / 8.10.5.2 — price table and idempotent charge generation
# ---------------------------------------------------------------------------


def test_set_service_price_requires_admin() -> None:
    clinic, admin, staff = _admin_and_staff()
    service = _service(clinic)
    with pytest.raises(PermissionDenied):
        finance_services.set_service_price(
            clinic_id=clinic.pk,
            actor=staff,
            service_id=service.pk,
            amount=Decimal("150.00"),
            currency="BRL",
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


def test_set_service_price_rejects_negative() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    with pytest.raises(ValidationError):
        finance_services.set_service_price(
            clinic_id=clinic.pk,
            actor=admin,
            service_id=service.pk,
            amount=Decimal("-1.00"),
            currency="BRL",
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


def test_generate_charge_captures_price_in_effect() -> None:
    """8.10.5.2: the price in effect at generation is preserved."""
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service, "150.00")
    appointment = _confirmed_appointment(clinic, service, unit, admin)

    charge = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    assert charge.amount == Decimal("150.00")
    assert charge.status == ChargeStatus.OPEN
    assert charge.due_date == timezone.localdate() + timedelta(days=7)


def test_generate_charge_is_idempotent() -> None:
    """8.10.5.2: repeated generation never duplicates a charge."""
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service)
    appointment = _confirmed_appointment(clinic, service, unit, admin)

    first = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )
    second = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    assert first.pk == second.pk
    assert Charge.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 1


def test_generate_charge_requires_confirmed_appointment() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service)
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente",
        birth_date=date(1990, 1, 1),
        email="p@example.test",
    )
    start = timezone.now() + timedelta(days=1)
    appointment = Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=admin.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status=AppointmentStatus.REQUESTED,
        idempotency_key=uuid4().hex,
        requested_by_id=admin.pk,
    )

    with pytest.raises(ValidationError):
        finance_services.generate_charge_for_appointment(
            clinic_id=clinic.pk,
            actor=admin,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


def test_generate_charge_requires_price() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    appointment = _confirmed_appointment(clinic, service, unit, admin)

    with pytest.raises(ValidationError):
        finance_services.generate_charge_for_appointment(
            clinic_id=clinic.pk,
            actor=admin,
            appointment_id=appointment.pk,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.10.5.3 / 8.10.5.4 — settlement, cancellation and audit
# ---------------------------------------------------------------------------


def test_settle_charge_records_actor_and_audit() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service)
    appointment = _confirmed_appointment(clinic, service, unit, admin)
    charge = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    settled = finance_services.settle_charge(
        clinic_id=clinic.pk, actor=admin, charge_id=charge.pk, request_id=uuid4()
    )

    assert settled.status == ChargeStatus.PAID
    assert settled.settled_by_id == admin.pk
    assert settled.settled_at is not None
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(action="update", resource_type="charge", resource_id=str(charge.pk))
        .exists()
    )


def test_cancel_charge_records_reason() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service)
    appointment = _confirmed_appointment(clinic, service, unit, admin)
    charge = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    canceled = finance_services.cancel_charge(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        reason="Consulta remarcada",
        request_id=uuid4(),
    )

    assert canceled.status == ChargeStatus.CANCELED
    assert canceled.cancel_reason == "Consulta remarcada"
    assert canceled.canceled_by_id == admin.pk


def test_settle_charge_denies_non_finance_role() -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    _price(clinic, service)
    appointment = _confirmed_appointment(clinic, service, unit, admin)
    charge = finance_services.generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        finance_services.settle_charge(
            clinic_id=clinic.pk, actor=outsider, charge_id=charge.pk, request_id=uuid4()
        )


def test_charge_cross_clinic_denied() -> None:
    clinic_a, admin_a, _staff_a = _admin_and_staff()
    clinic_b, admin_b, _staff_b = _admin_and_staff()
    service = _service(clinic_a)
    unit = _unit(clinic_a)
    _price(clinic_a, service)
    appointment = _confirmed_appointment(clinic_a, service, unit, admin_a)
    charge = finance_services.generate_charge_for_appointment(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        finance_services.settle_charge(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            charge_id=charge.pk,
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


def test_charge_list_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    _force_client(client, clinic, admin)
    response = client.get(reverse("charge_list"))
    assert response.status_code == 200
    assert "Contas a receber" in response.content.decode()


def test_service_price_create_http(client: Client) -> None:
    clinic, admin, _staff = _admin_and_staff()
    service = _service(clinic)
    _force_client(client, clinic, admin)
    response = client.post(
        reverse("service_price_create"),
        data={
            "service": str(service.pk),
            "amount": "200.00",
            "currency": "BRL",
            "valid_from": date.today().isoformat(),
        },
    )
    assert response.status_code == 302
    assert (
        ServicePrice.objects.for_clinic(clinic.pk)
        .filter(amount=Decimal("200.00"))
        .exists()
    )
