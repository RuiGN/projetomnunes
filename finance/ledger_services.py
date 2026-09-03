"""Transactional services for the ledger, reconciliation and closures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .ledger_models import (
    EntryKind,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEntry,
    PeriodClosure,
    ReconciliationMatch,
    StatementImport,
)

__all__ = [
    "Service",
    "balance_for_account",
    "close_period",
    "import_statement",
    "post_double_entry",
    "reconcile_automatically",
    "reopen_period",
]

DEFAULT_TOLERANCE = Decimal("0.00")

ACCOUNT_BLUEPRINT: tuple[tuple[str, str, str], ...] = (
    ("1.1.001", "Caixa geral", LedgerAccountKind.CASH),
    ("1.2.001", "Contas a receber", LedgerAccountKind.RECEIVABLE),
    ("4.1.001", "Receita de serviços", LedgerAccountKind.REVENUE),
    ("4.2.001", "Reembolsos concedidos", LedgerAccountKind.REFUND),
    ("5.1.001", "Taxas de provedor", LedgerAccountKind.FEE),
    ("5.2.001", "Repasses a profissionais", LedgerAccountKind.PAYOUT),
    ("5.3.001", "Ajustes de conciliação", LedgerAccountKind.ADJUSTMENT),
)


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


@transaction.atomic
def ensure_chart_of_accounts(*, clinic_id: UUID) -> None:
    """Idempotently provision the standard chart of accounts for one clinic."""
    for code, name, kind in ACCOUNT_BLUEPRINT:
        LedgerAccount.infrastructure_objects.get_or_create(
            clinic_id=clinic_id,
            code=code,
            defaults={"name": name, "kind": kind},
        )


@transaction.atomic
def post_double_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    debit_account_code: str,
    credit_account_code: str,
    amount: Decimal,
    currency: str,
    source_type: str,
    source_id: UUID,
    correlation_id: str = "",
    request_id: UUID,
) -> tuple[LedgerEntry, LedgerEntry]:
    """Post one balanced double entry atomically with an integrity digest."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    if amount <= 0:
        raise ValidationError("O valor do lançamento deve ser positivo.")
    if debit_account_code == credit_account_code:
        raise ValidationError("As contas de débito e crédito devem ser distintas.")
    ensure_chart_of_accounts(clinic_id=clinic_id)
    debit_account = LedgerAccount.infrastructure_objects.filter(
        clinic_id=clinic_id, code=debit_account_code
    ).first()
    credit_account = LedgerAccount.infrastructure_objects.filter(
        clinic_id=clinic_id, code=credit_account_code
    ).first()
    if debit_account is None or credit_account is None:
        raise ValidationError("Conta contábil não encontrada.")
    previous = (
        LedgerEntry.infrastructure_objects.filter(clinic_id=clinic_id)
        .order_by("-sequence")
        .first()
    )
    next_sequence = (previous.sequence + 1) if previous is not None else 1
    debit_entry = LedgerEntry(
        clinic_id=clinic_id,
        account_id=debit_account.pk,
        entry_kind=EntryKind.DEBIT,
        amount=amount,
        currency=currency.upper(),
        source_type=source_type,
        source_id=str(source_id),
        correlation_id=correlation_id,
        sequence=next_sequence,
        entry_hash="",
    )
    credit_entry = LedgerEntry(
        clinic_id=clinic_id,
        account_id=credit_account.pk,
        entry_kind=EntryKind.CREDIT,
        amount=amount,
        currency=currency.upper(),
        source_type=source_type,
        source_id=str(source_id),
        correlation_id=correlation_id,
        sequence=next_sequence + 1,
        entry_hash="",
    )
    debit_entry.entry_hash = debit_entry.expected_hash()
    credit_entry.entry_hash = credit_entry.expected_hash()
    debit_entry.full_clean(validate_unique=False, validate_constraints=False)
    debit_entry.save(force_insert=True)
    credit_entry.full_clean(validate_unique=False, validate_constraints=False)
    credit_entry.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="ledger_entry",
        resource_id=str(source_id),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return debit_entry, credit_entry


def balance_for_account(*, clinic_id: UUID, account_code: str) -> Decimal:
    """Return the signed balance (credits minus debits) of one account."""
    account = LedgerAccount.infrastructure_objects.filter(
        clinic_id=clinic_id, code=account_code
    ).first()
    if account is None:
        return Decimal("0.00")
    balance = Decimal("0.00")
    entries = LedgerEntry.infrastructure_objects.filter(
        clinic_id=clinic_id, account_id=account.pk
    )
    for entry in entries:
        if entry.entry_kind == EntryKind.CREDIT:
            balance += entry.amount
        else:
            balance -= entry.amount
    return balance


@transaction.atomic
def import_statement(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    provider: str,
    external_transactions: list[dict[str, str]],
    cursor: str,
    request_id: UUID,
) -> StatementImport:
    """Import one incremental provider statement with a cursor and checksum."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    import hashlib

    digest = hashlib.sha256(
        "".join(
            sorted(
                f"{tx.get('external_id', '')}:{tx.get('amount', '')}"
                for tx in external_transactions
            )
        ).encode("utf-8")
    ).hexdigest()
    imported = StatementImport.infrastructure_objects.create(
        clinic_id=clinic_id,
        provider=provider,
        cursor=cursor,
        checksum=digest,
        external_transaction_count=len(external_transactions),
        imported_by_id=actor.pk,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="statement_import",
        resource_id=str(imported.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return imported


@transaction.atomic
def reconcile_automatically(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    internal_source_type: str,
    internal_source_id: UUID,
    internal_amount: Decimal,
    external_transaction_id: str,
    external_amount: Decimal | None,
    currency: str = "BRL",
    tolerance: Decimal = DEFAULT_TOLERANCE,
    request_id: UUID,
) -> ReconciliationMatch:
    """Create or update one reconciliation match by identifiers and values."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    existing = ReconciliationMatch.infrastructure_objects.filter(
        clinic_id=clinic_id, external_transaction_id=external_transaction_id
    ).first()
    status = ReconciliationMatch.Status.PENDING
    if (
        external_amount is not None
        and abs(internal_amount - external_amount) <= tolerance
    ):
        status = ReconciliationMatch.Status.MATCHED
    elif external_amount is not None:
        status = ReconciliationMatch.Status.DIVERGENT
    if existing is not None:
        existing.status = status
        existing.external_amount = external_amount
        existing.save(update_fields=("status", "external_amount", "updated_at"))
        return existing
    match = ReconciliationMatch.infrastructure_objects.create(
        clinic_id=clinic_id,
        internal_source_type=internal_source_type,
        internal_source_id=str(internal_source_id),
        external_transaction_id=external_transaction_id,
        status=status,
        internal_amount=internal_amount,
        external_amount=external_amount,
        currency=currency,
        tolerance=tolerance,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="reconciliation_match",
        resource_id=str(match.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return match


@transaction.atomic
def close_period(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
    request_id: UUID,
) -> PeriodClosure:
    """Close one period with a locked balance derived from the ledger."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    if period_end < period_start:
        raise ValidationError("O período final deve ser igual ou posterior ao inicial.")
    if PeriodClosure.infrastructure_objects.filter(
        clinic_id=clinic_id, period_start=period_start, period_end=period_end
    ).exists():
        raise ValidationError("Este período já foi fechado.")
    balance = Decimal("0.00")
    for _code, _name, _kind in ACCOUNT_BLUEPRINT:
        balance += balance_for_account(clinic_id=clinic_id, account_code=_code)
    closure = PeriodClosure.infrastructure_objects.create(
        clinic_id=clinic_id,
        period_start=period_start,
        period_end=period_end,
        closed_balance=balance,
        closed_by_id=actor.pk,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="period_closure",
        resource_id=str(closure.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return closure


@transaction.atomic
def reopen_period(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    closure_id: UUID,
    request_id: UUID,
) -> PeriodClosure:
    """Reopen one closed period with an authorized, audited trail."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    closure = (
        PeriodClosure.infrastructure_objects.select_for_update()
        .filter(pk=closure_id, clinic_id=clinic_id)
        .first()
    )
    if closure is None:
        raise PermissionDenied
    if closure.is_reopened:
        return closure
    closure.is_reopened = True
    closure.reopened_by_id = actor.pk
    closure.reopened_at = timezone.now()
    closure.save(
        update_fields=("is_reopened", "reopened_by", "reopened_at", "updated_at")
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="period_closure",
        resource_id=str(closure.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return closure
