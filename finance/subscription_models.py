"""Subscription catalog and billing-cycle persistence.

Plans, price items, coupons and subscriptions are versioned and isolated per
organization. No card data (PAN/CVV) is ever persisted; the payment provider
is reached through an adapter that returns opaque tokens.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


class BillingInterval(models.TextChoices):
    MONTHLY = "monthly", "Mensal"
    QUARTERLY = "quarterly", "Trimestral"
    YEARLY = "yearly", "Anual"


class PlanStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    ACTIVE = "active", "Ativo"
    RETIRED = "retired", "Descontinuado"


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Em teste"
    ACTIVE = "active", "Ativa"
    PAST_DUE = "past_due", "Inadimplente"
    PAUSED = "paused", "Pausada"
    CANCELED = "canceled", "Cancelada"


class PlanQuerySet(models.QuerySet["Plan"]):
    def for_clinic(self, clinic_id: UUID) -> PlanQuerySet:
        return self.filter(clinic_id=clinic_id)


class PlanManager(models.Manager["Plan"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Plan queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PlanQuerySet:
        return PlanQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePlanManager(models.Manager["Plan"]):
    def get_queryset(self) -> PlanQuerySet:
        return PlanQuerySet(self.model, using=self._db)


class Plan(UUIDTimestampedModel):
    """One versioned commercial plan with a stable technical identifier."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="plans",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=PlanStatus.choices, default=PlanStatus.DRAFT
    )
    version = models.PositiveIntegerField(default=1)

    objects = PlanManager()
    infrastructure_objects = InfrastructurePlanManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "code", "version"),
                name="unique_plan_code_version_per_clinic",
            ),
        ]
        indexes = [
            models.Index(fields=("clinic", "code"), name="plan_clinic_code_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class PlanPriceQuerySet(models.QuerySet["PlanPrice"]):
    def for_clinic(self, clinic_id: UUID) -> PlanPriceQuerySet:
        return self.filter(clinic_id=clinic_id)


class PlanPriceManager(models.Manager["PlanPrice"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PlanPrice queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PlanPriceQuerySet:
        return PlanPriceQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePlanPriceManager(models.Manager["PlanPrice"]):
    def get_queryset(self) -> PlanPriceQuerySet:
        return PlanPriceQuerySet(self.model, using=self._db)


class PlanPrice(UUIDTimestampedModel):
    """One effective price item for a plan version."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="plan_prices",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="prices",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    interval = models.CharField(max_length=16, choices=BillingInterval.choices)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.0")
    )
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = PlanPriceManager()
    infrastructure_objects = InfrastructurePlanPriceManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="plan_price_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(tax_rate__gte=0), name="plan_price_tax_non_negative"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "plan", "valid_from"), name="plan_price_idx"
            ),
        ]


class CouponQuerySet(models.QuerySet["Coupon"]):
    def for_clinic(self, clinic_id: UUID) -> CouponQuerySet:
        return self.filter(clinic_id=clinic_id)


class CouponManager(models.Manager["Coupon"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Coupon queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> CouponQuerySet:
        return CouponQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureCouponManager(models.Manager["Coupon"]):
    def get_queryset(self) -> CouponQuerySet:
        return CouponQuerySet(self.model, using=self._db)


class Coupon(UUIDTimestampedModel):
    """One discount coupon with eligibility and validity."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="coupons",
    )
    code = models.CharField(max_length=64)
    discount_type = models.CharField(
        max_length=16, choices=(("percent", "Percentual"), ("fixed", "Fixo"))
    )
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)
    max_uses = models.PositiveIntegerField(default=0)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = CouponManager()
    infrastructure_objects = InfrastructureCouponManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "code"), name="unique_coupon_code_per_clinic"
            ),
            models.CheckConstraint(
                condition=Q(discount_value__gte=0), name="coupon_value_non_negative"
            ),
        ]


class SubscriptionQuerySet(models.QuerySet["Subscription"]):
    def for_clinic(self, clinic_id: UUID) -> SubscriptionQuerySet:
        return self.filter(clinic_id=clinic_id)


class SubscriptionManager(models.Manager["Subscription"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Subscription queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> SubscriptionQuerySet:
        return SubscriptionQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureSubscriptionManager(models.Manager["Subscription"]):
    def get_queryset(self) -> SubscriptionQuerySet:
        return SubscriptionQuerySet(self.model, using=self._db)


class Subscription(UUIDTimestampedModel):
    """One subscriber's dated contract with a plan, never storing card data."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=16,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.TRIALING,
    )
    provider_token = models.CharField(max_length=255, blank=True)
    current_period_start = models.DateField()
    current_period_end = models.DateField()
    trial_ends_at = models.DateField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    idempotency_key = models.CharField(max_length=64)

    objects = SubscriptionManager()
    infrastructure_objects = InfrastructureSubscriptionManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "idempotency_key"),
                name="unique_subscription_idempotency_per_clinic",
            ),
            models.CheckConstraint(
                condition=Q(current_period_end__gte=models.F("current_period_start")),
                name="subscription_period_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "subscriber", "status"),
                name="subscription_subscriber_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber_id}:{self.plan_id}:{self.status}"
