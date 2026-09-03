"""Acceptance tests for PRD 8.11.5 — relatórios financeiros e controles."""

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
from finance.models import Charge, ChargeStatus
from finance.payout_services import (
    approve_payout_batch,
    create_payout_batch,
    create_payout_rule,
)
from finance.reporting_services import (
    authorize_export_download,
    export_financial_csv,
    financial_dashboard,
)
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
    existing = Service.infrastructure_objects.filter(
        clinic_id=clinic.pk, name="Sessão"
    ).first()
    if existing is not None:
        return existing
    return Service.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Sessão", duration_minutes=50, buffer_minutes=10
    )


def _unit(clinic: Clinic) -> Unit:
    existing = Unit.infrastructure_objects.filter(
        clinic_id=clinic.pk, name="Unidade"
    ).first()
    if existing is not None:
        return existing
    return Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade", timezone_name="America/Sao_Paulo"
    )


def _paid_charge(clinic: Clinic, admin: User, amount: str = "100.00") -> Charge:
    from finance.models import ServicePrice

    service = _service(clinic)
    ServicePrice.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        amount=Decimal(amount),
        currency="BRL",
        valid_from=date.today() - timedelta(days=1),
    )
    profile = PatientProfile.infrastructure_objects.create(
        clinic_id=clinic.pk,
        full_name=f"Paciente {uuid4().hex[:8]}",
        birth_date=date(1990, 1, 1),
        email=f"p-{uuid4().hex[:8]}@example.test",
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
    settled = settle_charge(
        clinic_id=clinic.pk, actor=admin, charge_id=charge.pk, request_id=uuid4()
    )
    # Bring the due date inside the dashboard period under test.
    Charge.infrastructure_objects.filter(pk=settled.pk).update(
        due_date=date.today() - timedelta(days=1)
    )
    settled.refresh_from_db()
    return settled


# ---------------------------------------------------------------------------
# 8.11.5.1 — dashboard reconciles numerically with records
# ---------------------------------------------------------------------------


def test_dashboard_reconciles_with_charges() -> None:
    clinic, admin, _staff = _admin_staff()
    _paid_charge(clinic, admin, "100.00")
    _paid_charge(clinic, admin, "50.00")

    data = financial_dashboard(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
    )
    assert data.gross_revenue == Decimal("150.00")
    assert data.net_revenue == Decimal("150.00")
    assert data.receivable_open == Decimal("0.00")


def test_dashboard_counts_open_and_overdue() -> None:
    clinic, admin, _staff = _admin_staff()
    charge = _paid_charge(clinic, admin)
    charge.status = ChargeStatus.OPEN
    charge.save(update_fields=("status",))
    Charge.infrastructure_objects.filter(pk=charge.pk).update(
        due_date=date.today() - timedelta(days=1)
    )
    from finance.billing_services import mark_overdue_charges

    mark_overdue_charges(clinic_id=clinic.pk, actor=admin, request_id=uuid4())

    data = financial_dashboard(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
    )
    assert data.receivable_overdue == charge.net_amount
    assert data.receivable_open == Decimal("0.00")


def test_dashboard_includes_settled_payout() -> None:
    clinic, admin, staff = _admin_staff()
    therapist = staff
    service = _service(clinic)

    create_payout_rule(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        service_id=service.pk,
        percent_rate=Decimal("0.50"),
        fixed_amount=Decimal("0.00"),
        retention_rate=Decimal("0.00"),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    charge = _paid_charge(clinic, admin)
    batch = create_payout_batch(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        charges=[charge.pk],
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    approve_payout_batch(
        clinic_id=clinic.pk, actor=admin, batch_id=batch.pk, request_id=uuid4()
    )
    from finance.payout_services import settle_payout_batch

    settle_payout_batch(
        clinic_id=clinic.pk, actor=admin, batch_id=batch.pk, request_id=uuid4()
    )

    data = financial_dashboard(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
    )
    assert data.payout_settled == Decimal("50.00")


def test_dashboard_requires_admin() -> None:
    clinic, admin, staff = _admin_staff()
    with pytest.raises(PermissionDenied):
        financial_dashboard(
            clinic_id=clinic.pk,
            actor=staff,
            period_start=date.today() - timedelta(days=30),
            period_end=date.today(),
        )


def test_dashboard_rejects_inverted_period() -> None:
    clinic, admin, _staff = _admin_staff()
    with pytest.raises(ValidationError):
        financial_dashboard(
            clinic_id=clinic.pk,
            actor=admin,
            period_start=date.today(),
            period_end=date.today() - timedelta(days=30),
        )


# ---------------------------------------------------------------------------
# 8.11.5.2 — protected CSV export
# ---------------------------------------------------------------------------


def test_export_csv_and_download() -> None:
    clinic, admin, _staff = _admin_staff()
    _paid_charge(clinic, admin)
    handle = export_financial_csv(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    content = authorize_export_download(
        clinic_id=clinic.pk,
        actor=admin,
        export_id=handle.export_id,
        download_key=handle.download_key,
        request_id=uuid4(),
    )
    assert "gross_revenue" in content
    assert "100.00" in content
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(action="export", resource_type="finance_export")
        .exists()
    )


def test_export_download_wrong_key_denied() -> None:
    clinic, admin, _staff = _admin_staff()
    _paid_charge(clinic, admin)
    handle = export_financial_csv(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        authorize_export_download(
            clinic_id=clinic.pk,
            actor=admin,
            export_id=handle.export_id,
            download_key="wrong-key",
            request_id=uuid4(),
        )


def test_export_download_non_admin_denied() -> None:
    clinic, admin, staff = _admin_staff()
    _paid_charge(clinic, admin)
    handle = export_financial_csv(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        authorize_export_download(
            clinic_id=clinic.pk,
            actor=staff,
            export_id=handle.export_id,
            download_key=handle.download_key,
            request_id=uuid4(),
        )


def test_export_download_expired_denied() -> None:
    clinic, admin, _staff = _admin_staff()
    _paid_charge(clinic, admin)
    handle = export_financial_csv(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    from finance.reporting_services import _EXPORTS

    record = _EXPORTS[handle.export_id]
    record["expires_at"] = timezone.now() - timedelta(hours=1)
    with pytest.raises(PermissionDenied):
        authorize_export_download(
            clinic_id=clinic.pk,
            actor=admin,
            export_id=handle.export_id,
            download_key=handle.download_key,
            request_id=uuid4(),
        )


def test_export_download_cross_clinic_denied() -> None:
    clinic_a, admin_a, _staff_a = _admin_staff()
    clinic_b, admin_b, _staff_b = _admin_staff()
    _paid_charge(clinic_a, admin_a)
    handle = export_financial_csv(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        authorize_export_download(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            export_id=handle.export_id,
            download_key=handle.download_key,
            request_id=uuid4(),
        )
