"""Acceptance tests for PRD 8.11.3 — razão financeiro, conciliação e fechamento."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from finance.ledger_models import (
    EntryKind,
    LedgerEntry,
    ReconciliationMatch,
)
from finance.ledger_services import (
    balance_for_account,
    close_period,
    import_statement,
    post_double_entry,
    reconcile_automatically,
    reopen_period,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


# ---------------------------------------------------------------------------
# 8.11.3.1 — chart of accounts and double entry
# ---------------------------------------------------------------------------


def test_post_double_entry_is_balanced() -> None:
    """8.11.3.1: one debit and one credit of the same amount are posted."""
    clinic, admin = _admin()
    debit, credit = post_double_entry(
        clinic_id=clinic.pk,
        actor=admin,
        debit_account_code="1.1.001",
        credit_account_code="4.1.001",
        amount=Decimal("150.00"),
        currency="BRL",
        source_type="charge",
        source_id=uuid4(),
        request_id=uuid4(),
    )
    assert debit.entry_kind == EntryKind.DEBIT
    assert credit.entry_kind == EntryKind.CREDIT
    assert debit.amount == credit.amount == Decimal("150.00")
    assert LedgerEntry.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 2


def test_post_double_entry_rejects_same_account() -> None:
    clinic, admin = _admin()
    with pytest.raises(ValidationError):
        post_double_entry(
            clinic_id=clinic.pk,
            actor=admin,
            debit_account_code="1.1.001",
            credit_account_code="1.1.001",
            amount=Decimal("10.00"),
            currency="BRL",
            source_type="charge",
            source_id=uuid4(),
            request_id=uuid4(),
        )


def test_ledger_entries_are_append_only() -> None:
    clinic, admin = _admin()
    debit, _credit = post_double_entry(
        clinic_id=clinic.pk,
        actor=admin,
        debit_account_code="1.1.001",
        credit_account_code="4.1.001",
        amount=Decimal("50.00"),
        currency="BRL",
        source_type="charge",
        source_id=uuid4(),
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        debit.amount = Decimal("99.00")
        debit.save()


def test_ledger_balance_computes() -> None:
    """Asset accounts hold debits positively; revenue accounts mirror negatively."""
    clinic, admin = _admin()
    post_double_entry(
        clinic_id=clinic.pk,
        actor=admin,
        debit_account_code="1.1.001",
        credit_account_code="4.1.001",
        amount=Decimal("100.00"),
        currency="BRL",
        source_type="charge",
        source_id=uuid4(),
        request_id=uuid4(),
    )
    assert balance_for_account(clinic_id=clinic.pk, account_code="1.1.001") == Decimal(
        "-100.00"
    )
    assert balance_for_account(clinic_id=clinic.pk, account_code="4.1.001") == Decimal(
        "100.00"
    )


def test_ledger_cross_clinic_denied() -> None:
    clinic_a, admin_a = _admin()
    clinic_b, admin_b = _admin()
    with pytest.raises(PermissionDenied):
        post_double_entry(
            clinic_id=clinic_a.pk,
            actor=admin_b,
            debit_account_code="1.1.001",
            credit_account_code="4.1.001",
            amount=Decimal("10.00"),
            currency="BRL",
            source_type="charge",
            source_id=uuid4(),
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.3.2 — incremental statement import
# ---------------------------------------------------------------------------


def test_import_statement_records_cursor_and_checksum() -> None:
    clinic, admin = _admin()
    transactions = [
        {"external_id": "tx-1", "amount": "150.00"},
        {"external_id": "tx-2", "amount": "90.00"},
    ]
    imported = import_statement(
        clinic_id=clinic.pk,
        actor=admin,
        provider="fake",
        external_transactions=transactions,
        cursor="cursor-2",
        request_id=uuid4(),
    )
    assert imported.external_transaction_count == 2
    assert imported.cursor == "cursor-2"
    assert imported.checksum
    # Same content yields the same checksum (idempotent detection).
    again = import_statement(
        clinic_id=clinic.pk,
        actor=admin,
        provider="fake",
        external_transactions=list(reversed(transactions)),
        cursor="cursor-2",
        request_id=uuid4(),
    )
    assert again.checksum == imported.checksum


# ---------------------------------------------------------------------------
# 8.11.3.3 — reconciliation states
# ---------------------------------------------------------------------------


def test_reconciliation_matches_within_tolerance() -> None:
    clinic, admin = _admin()
    match = reconcile_automatically(
        clinic_id=clinic.pk,
        actor=admin,
        internal_source_type="charge",
        internal_source_id=uuid4(),
        internal_amount=Decimal("150.00"),
        external_transaction_id="tx-1",
        external_amount=Decimal("150.00"),
        request_id=uuid4(),
    )
    assert match.status == ReconciliationMatch.Status.MATCHED


def test_reconciliation_flags_divergence() -> None:
    clinic, admin = _admin()
    match = reconcile_automatically(
        clinic_id=clinic.pk,
        actor=admin,
        internal_source_type="charge",
        internal_source_id=uuid4(),
        internal_amount=Decimal("150.00"),
        external_transaction_id="tx-2",
        external_amount=Decimal("120.00"),
        request_id=uuid4(),
    )
    assert match.status == ReconciliationMatch.Status.DIVERGENT


def test_reconciliation_is_idempotent_by_external_id() -> None:
    clinic, admin = _admin()
    first = reconcile_automatically(
        clinic_id=clinic.pk,
        actor=admin,
        internal_source_type="charge",
        internal_source_id=uuid4(),
        internal_amount=Decimal("100.00"),
        external_transaction_id="tx-3",
        external_amount=Decimal("100.00"),
        request_id=uuid4(),
    )
    second = reconcile_automatically(
        clinic_id=clinic.pk,
        actor=admin,
        internal_source_type="charge",
        internal_source_id=uuid4(),
        internal_amount=Decimal("100.00"),
        external_transaction_id="tx-3",
        external_amount=Decimal("100.00"),
        request_id=uuid4(),
    )
    assert first.pk == second.pk


# ---------------------------------------------------------------------------
# 8.11.3.4 — period closure and authorized reopen
# ---------------------------------------------------------------------------


def test_close_period_locks_balance() -> None:
    clinic, admin = _admin()
    post_double_entry(
        clinic_id=clinic.pk,
        actor=admin,
        debit_account_code="1.1.001",
        credit_account_code="4.1.001",
        amount=Decimal("200.00"),
        currency="BRL",
        source_type="charge",
        source_id=uuid4(),
        request_id=uuid4(),
    )
    closure = close_period(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    assert closure.closed_balance == Decimal("0.00")  # balanced ledger


def test_close_period_rejects_duplicate() -> None:
    clinic, admin = _admin()
    start = date.today() - timedelta(days=30)
    close_period(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=start,
        period_end=date.today(),
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        close_period(
            clinic_id=clinic.pk,
            actor=admin,
            period_start=start,
            period_end=date.today(),
            request_id=uuid4(),
        )


def test_reopen_period_records_trail() -> None:
    clinic, admin = _admin()
    closure = close_period(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=date.today() - timedelta(days=30),
        period_end=date.today(),
        request_id=uuid4(),
    )
    reopened = reopen_period(
        clinic_id=clinic.pk, actor=admin, closure_id=closure.pk, request_id=uuid4()
    )
    assert reopened.is_reopened is True
    assert reopened.reopened_by_id == admin.pk
    assert reopened.reopened_at is not None
