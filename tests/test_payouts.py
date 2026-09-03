"""Acceptance tests for PRD 8.11.4 — repasses, comissões e documentos fiscais."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from finance.models import Charge
from finance.payout_models import FiscalDocument, PayoutBatch, PayoutRule
from finance.payout_services import (
    approve_payout_batch,
    cancel_fiscal_document,
    create_payout_batch,
    create_payout_rule,
    issue_fiscal_document,
    settle_payout_batch,
)
from people.models import PatientProfile
from scheduling.models import Service, Unit
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin_therapist() -> tuple[Clinic, User, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    return clinic, admin, therapist


def _service(clinic: Clinic) -> Service:
    return Service.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Sessão", duration_minutes=50, buffer_minutes=10
    )


def _unit(clinic: Clinic) -> Unit:
    return Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade", timezone_name="America/Sao_Paulo"
    )


def _paid_charge(clinic: Clinic, admin: User, service: Service) -> Charge:
    from finance.models import ServicePrice
    from finance.services import generate_charge_for_appointment, settle_charge

    ServicePrice.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        amount=Decimal("100.00"),
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
    from scheduling.models import Appointment

    appointment = Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=admin.pk,
        patient_profile_id=profile.pk,
        unit_id=_unit(clinic).pk,
        start_at=start,
        end_at=start + timedelta(minutes=50),
        status="confirmed",
        idempotency_key=uuid4().hex,
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


def _rule(clinic: Clinic, admin: User, therapist: User, service: Service) -> PayoutRule:
    return create_payout_rule(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        service_id=service.pk,
        percent_rate=Decimal("0.50"),
        fixed_amount=Decimal("0.00"),
        retention_rate=Decimal("0.10"),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# 8.11.4.1 — versioned split rules
# ---------------------------------------------------------------------------


def test_create_payout_rule_versions() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    first = _rule(clinic, admin, therapist, service)
    second = _rule(clinic, admin, therapist, service)
    assert first.version == 1
    assert second.version == 2


def test_create_payout_rule_rejects_invalid_rate() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    with pytest.raises(ValidationError):
        create_payout_rule(
            clinic_id=clinic.pk,
            actor=admin,
            professional_id=therapist.pk,
            service_id=service.pk,
            percent_rate=Decimal("1.5"),
            fixed_amount=Decimal("0.00"),
            retention_rate=Decimal("0.0"),
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.4.2 — payout batches with calculation memory
# ---------------------------------------------------------------------------


def test_payout_batch_calculates_item_memory() -> None:
    """8.11.4.2: the batch records item-by-item memory of the calculation."""
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    _rule(clinic, admin, therapist, service)
    charge = _paid_charge(clinic, admin, service)

    batch = create_payout_batch(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        charges=[charge.pk],
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )

    assert len(batch.calculation_memory) == 1
    item = batch.calculation_memory[0]
    assert Decimal(str(item["amount"])) == Decimal("100.00")
    assert Decimal(str(item["gross"])) == Decimal("50.00")
    assert Decimal(str(item["retention"])) == Decimal("5.00")
    assert Decimal(str(item["net"])) == Decimal("45.00")
    assert batch.total_amount == Decimal("45.00")
    assert batch.status == PayoutBatch.Status.DRAFT


def test_payout_batch_is_idempotent() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    _rule(clinic, admin, therapist, service)
    charge = _paid_charge(clinic, admin, service)
    key = uuid4().hex

    first = create_payout_batch(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        charges=[charge.pk],
        idempotency_key=key,
        request_id=uuid4(),
    )
    second = create_payout_batch(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        charges=[charge.pk],
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert first.pk == second.pk


def test_payout_batch_rejects_unpaid_charge() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    _rule(clinic, admin, therapist, service)
    charge = _paid_charge(clinic, admin, service)
    Charge.infrastructure_objects.filter(pk=charge.pk).update(status="open")
    with pytest.raises(ValidationError):
        create_payout_batch(
            clinic_id=clinic.pk,
            actor=admin,
            professional_id=therapist.pk,
            charges=[charge.pk],
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


def test_payout_batch_requires_rule() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    charge = _paid_charge(clinic, admin, service)
    with pytest.raises(ValidationError):
        create_payout_batch(
            clinic_id=clinic.pk,
            actor=admin,
            professional_id=therapist.pk,
            charges=[charge.pk],
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.4.3 — approval and settlement
# ---------------------------------------------------------------------------


def test_payout_settlement_requires_approval_and_posts_ledger() -> None:
    clinic, admin, therapist = _admin_therapist()
    service = _service(clinic)
    _rule(clinic, admin, therapist, service)
    charge = _paid_charge(clinic, admin, service)
    batch = create_payout_batch(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        charges=[charge.pk],
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )

    with pytest.raises(ValidationError):
        settle_payout_batch(
            clinic_id=clinic.pk, actor=admin, batch_id=batch.pk, request_id=uuid4()
        )

    approved = approve_payout_batch(
        clinic_id=clinic.pk, actor=admin, batch_id=batch.pk, request_id=uuid4()
    )
    assert approved.status == PayoutBatch.Status.APPROVED
    assert approved.approved_by_id == admin.pk

    settled = settle_payout_batch(
        clinic_id=clinic.pk, actor=admin, batch_id=batch.pk, request_id=uuid4()
    )
    assert settled.status == PayoutBatch.Status.SETTLED
    assert settled.settled_at is not None


def test_payout_cross_clinic_denied() -> None:
    """A batch whose charges belong to another clinic is denied outright."""
    clinic_a, admin_a, therapist_a = _admin_therapist()
    clinic_b, admin_b, _therapist_b = _admin_therapist()
    service = _service(clinic_a)
    _rule(clinic_a, admin_a, therapist_a, service)
    charge = _paid_charge(clinic_a, admin_a, service)
    with pytest.raises(ValidationError):
        create_payout_batch(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            professional_id=therapist_a.pk,
            charges=[charge.pk],
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.4.4 — fiscal documents
# ---------------------------------------------------------------------------


def test_issue_fiscal_document_idempotent() -> None:
    clinic, admin, _therapist = _admin_therapist()
    service = _service(clinic)
    charge = _paid_charge(clinic, admin, service)
    key = uuid4().hex

    first = issue_fiscal_document(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        document_type="invoice",
        idempotency_key=key,
        request_id=uuid4(),
    )
    second = issue_fiscal_document(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        document_type="invoice",
        idempotency_key=key,
        request_id=uuid4(),
    )
    assert first.pk == second.pk
    assert first.status == FiscalDocument.Status.ISSUED
    assert first.document_number


def test_invoice_requires_paid_charge() -> None:
    clinic, admin, _therapist = _admin_therapist()
    service = _service(clinic)
    charge = _paid_charge(clinic, admin, service)
    Charge.infrastructure_objects.filter(pk=charge.pk).update(status="open")
    with pytest.raises(ValidationError):
        issue_fiscal_document(
            clinic_id=clinic.pk,
            actor=admin,
            charge_id=charge.pk,
            document_type="invoice",
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


def test_cancel_fiscal_document() -> None:
    clinic, admin, _therapist = _admin_therapist()
    service = _service(clinic)
    charge = _paid_charge(clinic, admin, service)
    document = issue_fiscal_document(
        clinic_id=clinic.pk,
        actor=admin,
        charge_id=charge.pk,
        document_type="receipt",
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    canceled = cancel_fiscal_document(
        clinic_id=clinic.pk, actor=admin, document_id=document.pk, request_id=uuid4()
    )
    assert canceled.status == FiscalDocument.Status.CANCELED
