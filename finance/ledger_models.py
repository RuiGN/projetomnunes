"""Double-entry ledger and reconciliation persistence.

Ledger entries are append-only: services and model interfaces forbid updates
and deletes once created. Each entry references its causal source (charge,
refund, fee, payout, adjustment) and a signed digest protects integrity.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


class LedgerAccountKind(models.TextChoices):
    CASH = "cash", "Caixa"
    RECEIVABLE = "receivable", "Contas a receber"
    REVENUE = "revenue", "Receita"
    REFUND = "refund", "Reembolso"
    FEE = "fee", "Taxa"
    PAYOUT = "payout", "Repasse"
    ADJUSTMENT = "adjustment", "Ajuste"


class EntryKind(models.TextChoices):
    DEBIT = "debit", "Débito"
    CREDIT = "credit", "Crédito"


class LedgerAccountQuerySet(models.QuerySet["LedgerAccount"]):
    def for_clinic(self, clinic_id: UUID) -> LedgerAccountQuerySet:
        return self.filter(clinic_id=clinic_id)


class LedgerAccountManager(models.Manager["LedgerAccount"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("LedgerAccount queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> LedgerAccountQuerySet:
        return LedgerAccountQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureLedgerAccountManager(models.Manager["LedgerAccount"]):
    def get_queryset(self) -> LedgerAccountQuerySet:
        return LedgerAccountQuerySet(self.model, using=self._db)


class LedgerAccount(UUIDTimestampedModel):
    """One double-entry account inside a tenant's chart of accounts."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ledger_accounts",
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=LedgerAccountKind.choices)

    objects = LedgerAccountManager()
    infrastructure_objects = InfrastructureLedgerAccountManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "code"), name="unique_account_code_per_clinic"
            ),
        ]


class LedgerEntryQuerySet(models.QuerySet["LedgerEntry"]):
    def for_clinic(self, clinic_id: UUID) -> LedgerEntryQuerySet:
        return self.filter(clinic_id=clinic_id)


class LedgerEntryManager(models.Manager["LedgerEntry"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("LedgerEntry queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> LedgerEntryQuerySet:
        return LedgerEntryQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureLedgerEntryManager(models.Manager["LedgerEntry"]):
    def get_queryset(self) -> LedgerEntryQuerySet:
        return LedgerEntryQuerySet(self.model, using=self._db)


class LedgerEntry(UUIDTimestampedModel):
    """One append-only double-entry posting linked to its causal source."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    account = models.ForeignKey(
        LedgerAccount,
        on_delete=models.PROTECT,
        related_name="entries",
    )
    entry_kind = models.CharField(max_length=8, choices=EntryKind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=64)
    correlation_id = models.CharField(max_length=64, blank=True)
    sequence = models.PositiveBigIntegerField()
    entry_hash = models.CharField(max_length=64)

    objects = LedgerEntryManager()
    infrastructure_objects = InfrastructureLedgerEntryManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "sequence"), name="unique_ledger_sequence_per_clinic"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="ledger_amount_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "source_type", "source_id"),
                name="ledger_source_idx",
            ),
            models.Index(
                fields=("clinic", "account", "created_at"), name="ledger_account_idx"
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow only the initial append; settled entries are immutable."""
        if not self._state.adding:
            raise PermissionDenied("Ledger entries are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject deletion of append-only ledger entries."""
        raise PermissionDenied("Ledger entries are append-only.")

    def expected_hash(self) -> str:
        """Return the deterministic integrity digest for this entry."""
        import hashlib

        payload = (
            f"{self.clinic_id}:{self.sequence}:{self.account_id}:{self.entry_kind}:"
            f"{self.amount}:{self.source_type}:{self.source_id}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StatementImportQuerySet(models.QuerySet["StatementImport"]):
    def for_clinic(self, clinic_id: UUID) -> StatementImportQuerySet:
        return self.filter(clinic_id=clinic_id)


class StatementImportManager(models.Manager["StatementImport"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("StatementImport queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> StatementImportQuerySet:
        return StatementImportQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureStatementImportManager(models.Manager["StatementImport"]):
    def get_queryset(self) -> StatementImportQuerySet:
        return StatementImportQuerySet(self.model, using=self._db)


class StatementImport(UUIDTimestampedModel):
    """One incremental provider-statement import with a cursor and checksum."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="statement_imports",
    )
    provider = models.CharField(max_length=64)
    cursor = models.CharField(max_length=255, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    external_transaction_count = models.PositiveIntegerField(default=0)
    imported_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="statement_imports",
    )

    objects = StatementImportManager()
    infrastructure_objects = InfrastructureStatementImportManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "provider", "created_at"), name="statement_idx"
            ),
        ]


class ReconciliationMatchQuerySet(models.QuerySet["ReconciliationMatch"]):
    def for_clinic(self, clinic_id: UUID) -> ReconciliationMatchQuerySet:
        return self.filter(clinic_id=clinic_id)


class ReconciliationMatchManager(models.Manager["ReconciliationMatch"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "ReconciliationMatch queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ReconciliationMatchQuerySet:
        return ReconciliationMatchQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureReconciliationMatchManager(models.Manager["ReconciliationMatch"]):
    def get_queryset(self) -> ReconciliationMatchQuerySet:
        return ReconciliationMatchQuerySet(self.model, using=self._db)


class ReconciliationMatch(UUIDTimestampedModel):
    """One internal-to-external reconciliation with an explicit state."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        MATCHED = "matched", "Conciliado"
        DIVERGENT = "divergent", "Divergente"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="reconciliation_matches",
    )
    internal_source_type = models.CharField(max_length=64)
    internal_source_id = models.CharField(max_length=64)
    external_transaction_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    internal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    external_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    currency = models.CharField(max_length=3, default="BRL")
    tolerance = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_decisions",
    )

    objects = ReconciliationMatchManager()
    infrastructure_objects = InfrastructureReconciliationMatchManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "external_transaction_id"),
                name="unique_reconciliation_external_per_clinic",
            ),
        ]
        indexes = [
            models.Index(fields=("clinic", "status"), name="reconciliation_status_idx"),
        ]


class PeriodClosureQuerySet(models.QuerySet["PeriodClosure"]):
    def for_clinic(self, clinic_id: UUID) -> PeriodClosureQuerySet:
        return self.filter(clinic_id=clinic_id)


class PeriodClosureManager(models.Manager["PeriodClosure"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PeriodClosure queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PeriodClosureQuerySet:
        return PeriodClosureQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePeriodClosureManager(models.Manager["PeriodClosure"]):
    def get_queryset(self) -> PeriodClosureQuerySet:
        return PeriodClosureQuerySet(self.model, using=self._db)


class PeriodClosure(UUIDTimestampedModel):
    """One closed period with locked balances and an authorized reopen trail."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="period_closures",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    closed_balance = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    closed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="period_closures_made",
    )
    reopened_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="period_closures_reopened",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    is_reopened = models.BooleanField(default=False)

    objects = PeriodClosureManager()
    infrastructure_objects = InfrastructurePeriodClosureManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "period_start", "period_end"),
                name="unique_period_closure_per_clinic",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=models.F("period_start")),
                name="closure_period_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "period_start", "period_end"), name="closure_idx"
            ),
        ]
