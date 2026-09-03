"""Acceptance tests for PRD 8.11.2 — cobranças avulsas, inadimplência e reembolsos."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from finance.billing_services import (
    approve_refund,
    create_ad_hoc_charge,
    enqueue_exception,
    mark_overdue_charges,
    reject_refund,
    request_refund,
    resolve_exception,
)
from finance.models import AdHocCharge, Charge, ChargeStatus, RefundKind, RefundStatus
from finance.services import generate_charge_for_appointment, settle_charge
from people.models import PatientProfile
from scheduling.models import Service, Unit
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin_staff() -> tuple[Clinic, User, User]:
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
        clinic_id=clinic.pk, name="Sessão", duration_minutes=50, buffer_minutes=10
    )


def _unit(clinic: Clinic) -> Unit:
    return Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade", timezone_name="America/Sao_Paulo"
    )


def _paid_charge(clinic: Clinic, admin: User, amount: str = "150.00") -> Charge:
    from datetime import date

    from finance.models import ServicePrice

    service = _service(clinic)
    unit = _unit(clinic)
    ServicePrice.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        amount=Decimal(amount),
        currency="BRL",
        valid_from=date.today() - timedelta(days=1),
    )
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente",
        birth_date=date(1990, 1, 1),
        email="p@example.test",
    )
    start = timezone.now() + timedelta(days=1)
    appointment = __import__(
        "scheduling.models", fromlist=["Appointment"]
    ).Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=admin.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status="confirmed",
        idempotency_key=__import__("uuid", fromlist=["uuid4"]).uuid4().hex,
        requested_by_id=admin.pk,
    )
    charge = generate_charge_for_appointment(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        request_id=uuid4(),
    )
    return settle_charge(
        clinic_id=clinic.pk, actor=admin, charge_id=charge.pk, request_id=uuid4()
    )


# ---------------------------------------------------------------------------
# 8.11.2.1 — ad-hoc charges with idempotency
# ---------------------------------------------------------------------------


def test_create_ad_hoc_charge_is_idempotent() -> None:
    clinic, admin, _staff = _admin_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente",
        birth_date=date(1990, 1, 1),
        email="p@example.test",
    )
    from scheduling.models import Appointment

    start = (
        timezone.now() + timezone.timedelta(days=1)
        if False
        else timezone.now()
        + __import__("datetime", fromlist=["timedelta"]).timedelta(days=1)
    )
    appointment = Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=admin.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start
        + __import__("datetime", fromlist=["timedelta"]).timedelta(minutes=50),
        status="confirmed",
        idempotency_key=uuid4().hex,
        requested_by_id=admin.pk,
    )
    key = uuid4().hex
    first = create_ad_hoc_charge(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        description="Taxa de material",
        amount=Decimal("30.00"),
        currency="BRL",
        due_date=date.today(),
        idempotency_key=key,
        request_id=uuid4(),
    )
    second = create_ad_hoc_charge(
        clinic_id=clinic.pk,
        actor=admin,
        appointment_id=appointment.pk,
        description="Taxa de material",
        amount=Decimal("30.00"),
        currency="BRL",
        due_date=date.today(),
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert first.pk == second.pk
    assert AdHocCharge.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 1


def test_create_ad_hoc_charge_rejects_negative() -> None:
    clinic, admin, _staff = _admin_staff()
    service = _service(clinic)
    unit = _unit(clinic)
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name="Paciente",
        birth_date=date(1990, 1, 1),
        email="p@example.test",
    )

    from scheduling.models import Appointment

    start = timezone.now() + timedelta(days=1)
    appointment = Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=admin.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status="confirmed",
        idempotency_key=uuid4().hex,
        requested_by_id=admin.pk,
    )
    with pytest.raises(ValidationError):
        create_ad_hoc_charge(
            clinic_id=clinic.pk,
            actor=admin,
            appointment_id=appointment.pk,
            description="Taxa",
            amount=Decimal("-1.00"),
            currency="BRL",
            due_date=date.today(),
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.2.2 — delinquency ruler
# ---------------------------------------------------------------------------


def test_mark_overdue_charges_flips_open_past_due() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    charge.status = ChargeStatus.OPEN
    charge.save(update_fields=("status",))
    charge.refresh_from_db()
    # Force the charge into the past due date.
    Charge.infrastructure_objects.filter(pk=charge.pk).update(
        due_date=date.today() - timezone.timedelta(days=1)
        if False
        else date.today()
        - __import__("datetime", fromlist=["timedelta"]).timedelta(days=1)
    )
    charge.refresh_from_db()

    count = mark_overdue_charges(clinic_id=clinic.pk, actor=admin, request_id=uuid4())

    assert count >= 1
    charge.refresh_from_db()
    assert charge.status == ChargeStatus.OVERDUE


# ---------------------------------------------------------------------------
# 8.11.2.3 — refunds with justification and approval
# ---------------------------------------------------------------------------


def test_request_refund_requires_justification() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    with pytest.raises(ValidationError):
        request_refund(
            clinic_id=clinic.pk,
            actor=admin,
            charge_id=charge.pk,
            kind=RefundKind.PARTIAL,
            amount=Decimal("50.00"),
            justification="  ",
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


def test_request_refund_rejects_amount_above_charge() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    with pytest.raises(ValidationError):
        request_refund(
            clinic_id=clinic.pk,
            actor=admin,
            charge_id=charge.pk,
            kind=RefundKind.FULL,
            amount=Decimal("999.00"),
            justification="Erro de cobrança",
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


def test_refund_lifecycle_approve_and_reject() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    refund = request_refund(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        kind=RefundKind.FULL,
        amount=charge.net_amount,
        justification="Erro de cobrança",
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    assert refund.status == RefundStatus.PENDING

    approved = approve_refund(
        clinic_id=clinic.pk, actor=admin, refund_id=refund.pk, request_id=uuid4()
    )
    assert approved.status == RefundStatus.APPROVED
    assert approved.decided_by_id == admin.pk
    charge.refresh_from_db()
    assert charge.status == ChargeStatus.CANCELED


def test_refund_rejection_path() -> None:
    """A second refund on another paid charge can be rejected."""
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    refund = request_refund(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        kind=RefundKind.PARTIAL,
        amount=Decimal("10.00"),
        justification="Teste",
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    rejected = reject_refund(
        clinic_id=clinic.pk, actor=admin, refund_id=refund.pk, request_id=uuid4()
    )
    assert rejected.status == RefundStatus.REJECTED
    assert rejected.decided_by_id == admin.pk
    charge.refresh_from_db()
    assert charge.status == ChargeStatus.PAID


def test_refund_idempotent() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    key = uuid4().hex
    first = request_refund(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        kind=RefundKind.PARTIAL,
        amount=Decimal("10.00"),
        justification="Duplicidade",
        idempotency_key=key,
        request_id=uuid4(),
    )
    second = request_refund(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        kind=RefundKind.PARTIAL,
        amount=Decimal("10.00"),
        justification="Duplicidade",
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert first.pk == second.pk


def test_refund_cross_clinic_denied() -> None:
    clinic_a, admin_a, _staff_a = _admin_staff()
    clinic_b, admin_b, _staff_b = _admin_staff()
    charge = _paid_charge(clinic_a, admin_a)
    with pytest.raises(PermissionDenied):
        request_refund(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            charge_id=charge.pk,
            kind=RefundKind.FULL,
            amount=charge.net_amount,
            justification="Invasão",
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.2.4 — exception queue
# ---------------------------------------------------------------------------


def test_exception_queue_enqueue_and_resolve() -> None:
    clinic, admin, _staff = _admin_staff()
    item = enqueue_exception(
        clinic_id=clinic.pk,
        kind="orphan_charge",
        reference="charge-999",
        detail={"amount": "10.00"},
    )
    assert item.status == "open"

    resolved = resolve_exception(
        clinic_id=clinic.pk, actor=admin, item_id=item.pk, request_id=uuid4()
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_by_id == admin.pk


def test_exception_resolution_audits() -> None:
    clinic, admin, _staff = _admin_staff()
    item = enqueue_exception(
        clinic_id=clinic.pk, kind="invalid_webhook", reference="evt-1"
    )
    resolve_exception(
        clinic_id=clinic.pk, actor=admin, item_id=item.pk, request_id=uuid4()
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(resource_type="exception_queue_item", resource_id=str(item.pk))
        .exists()
    )
