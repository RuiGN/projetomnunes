"""Finance persistence: service prices and accounts receivable.

Prices and charges are kept strictly separate from clinical data. A charge is
generated idempotently from a confirmed appointment and records the price in
effect at generation time, never mutating historical amounts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel

from .billing_models import (  # noqa: F401
    AdHocCharge,
    ExceptionQueueItem,
    RefundKind,
    RefundRequest,
    RefundStatus,
)
from .ledger_models import (  # noqa: F401
    EntryKind,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEntry,
    PeriodClosure,
    ReconciliationMatch,
    StatementImport,
)
from .payout_models import (  # noqa: F401
    FiscalDocument,
    PayoutBatch,
    PayoutRule,
)
from .subscription_models import (  # noqa: F401
    BillingInterval,
    Coupon,
    Plan,
    PlanPrice,
    PlanStatus,
    Subscription,
    SubscriptionStatus,
)
from .webhook_models import (  # noqa: F401
    WebhookEvent,
    WebhookStatus,
)

__all__ = [
    "AdHocCharge",
    "BillingInterval",
    "Charge",
    "ChargeStatus",
    "Coupon",
    "EntryKind",
    "ExceptionQueueItem",
    "FiscalDocument",
    "LedgerAccount",
    "LedgerAccountKind",
    "LedgerEntry",
    "PayoutBatch",
    "PayoutRule",
    "PeriodClosure",
    "Plan",
    "PlanPrice",
    "PlanStatus",
    "ReconciliationMatch",
    "RefundKind",
    "RefundRequest",
    "RefundStatus",
    "ServicePrice",
    "StatementImport",
    "Subscription",
    "SubscriptionStatus",
    "WebhookEvent",
    "WebhookStatus",
]


class ChargeStatus(models.TextChoices):
    OPEN = "open", "Em aberto"
    PAID = "paid", "Pago"
    OVERDUE = "overdue", "Vencido"
    CANCELED = "canceled", "Cancelado"


class ServicePriceQuerySet(models.QuerySet["ServicePrice"]):
    def for_clinic(self, clinic_id: UUID) -> ServicePriceQuerySet:
        return self.filter(clinic_id=clinic_id)


class ServicePriceManager(models.Manager["ServicePrice"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ServicePrice queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ServicePriceQuerySet:
        return ServicePriceQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureServicePriceManager(models.Manager["ServicePrice"]):
    def get_queryset(self) -> ServicePriceQuerySet:
        return ServicePriceQuerySet(self.model, using=self._db)


class ServicePrice(UUIDTimestampedModel):
    """One effective price for a bookable service, versioned by validity."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="service_prices",
    )
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.PROTECT,
        related_name="prices",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = ServicePriceManager()
    infrastructure_objects = InfrastructureServicePriceManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="service_price_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="service_price_valid_dates",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "service", "valid_from"),
                name="price_clinic_service_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.service_id}:{self.amount}"


class ChargeQuerySet(models.QuerySet["Charge"]):
    def for_clinic(self, clinic_id: UUID) -> ChargeQuerySet:
        return self.filter(clinic_id=clinic_id)


class ChargeManager(models.Manager["Charge"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Charge queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ChargeQuerySet:
        return ChargeQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureChargeManager(models.Manager["Charge"]):
    def get_queryset(self) -> ChargeQuerySet:
        return ChargeQuerySet(self.model, using=self._db)


class Charge(UUIDTimestampedModel):
    """One accounts-receivable entry generated from a confirmed appointment."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="charges",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.PROTECT,
        related_name="charges",
    )
    service = models.ForeignKey(
        "scheduling.Service",
        on_delete=models.PROTECT,
        related_name="charges",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    due_date = models.DateField()
    status = models.CharField(
        max_length=16, choices=ChargeStatus.choices, default=ChargeStatus.OPEN
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    discount_justification = models.CharField(max_length=255, blank=True)
    settled_at = models.DateTimeField(blank=True, null=True)
    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settled_charges",
    )
    canceled_at = models.DateTimeField(blank=True, null=True)
    canceled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="canceled_charges",
    )
    cancel_reason = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=64)

    objects = ChargeManager()
    infrastructure_objects = InfrastructureChargeManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_charge_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="charge_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="charge_discount_non_negative",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "due_date"),
                name="charge_clinic_status_due_idx",
            ),
            models.Index(
                fields=("clinic", "appointment"),
                name="charge_clinic_appointment_idx",
            ),
        ]

    @property
    def net_amount(self) -> Decimal:
        """Return the amount after the justified discount."""
        return self.amount - self.discount_amount

    def __str__(self) -> str:
        return f"{self.service_id}:{self.status}"
