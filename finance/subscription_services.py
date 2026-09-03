"""Transactional services for the subscription catalog and billing cycle."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .models import (
    BillingInterval,
    Plan,
    PlanPrice,
    PlanStatus,
    Subscription,
    SubscriptionStatus,
)

__all__ = [
    "Service",
    "cancel_subscription",
    "create_plan",
    "create_plan_price",
    "create_subscription",
    "pause_subscription",
    "renew_subscription",
]


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


def _interval_days(interval: str) -> int:
    return {
        BillingInterval.MONTHLY: 30,
        BillingInterval.QUARTERLY: 90,
        BillingInterval.YEARLY: 365,
    }[BillingInterval(interval)]


@transaction.atomic
def create_plan(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    code: str,
    name: str,
    description: str,
    request_id: UUID,
) -> Plan:
    """Create one versioned plan."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized = code.strip().lower()
    if not normalized or not name.strip():
        raise ValidationError("Informe código e nome do plano.")
    latest = (
        Plan.infrastructure_objects.filter(clinic_id=clinic_id, code=normalized)
        .order_by("-version")
        .first()
    )
    version = (latest.version + 1) if latest is not None else 1
    plan = Plan.infrastructure_objects.create(
        clinic_id=clinic_id,
        code=normalized,
        name=name.strip(),
        description=description.strip(),
        status=PlanStatus.DRAFT,
        version=version,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="plan",
        resource_id=str(plan.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return plan


@transaction.atomic
def create_plan_price(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    plan_id: UUID,
    amount: Decimal,
    currency: str,
    interval: str,
    tax_rate: Decimal,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> PlanPrice:
    """Create one effective price item for a plan version."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    plan = Plan.infrastructure_objects.filter(pk=plan_id, clinic_id=clinic_id).first()
    if plan is None:
        raise ValidationError("Plano não encontrado.")
    if amount < 0 or tax_rate < 0:
        raise ValidationError("Valores não podem ser negativos.")
    if interval not in BillingInterval.values:
        raise ValidationError("Intervalo de cobrança inválido.")
    if valid_until is not None and valid_until < valid_from:
        raise ValidationError("A data final não pode ser anterior à inicial.")
    price = PlanPrice.infrastructure_objects.create(
        clinic_id=clinic_id,
        plan_id=plan.pk,
        amount=amount,
        currency=currency.upper(),
        interval=interval,
        tax_rate=tax_rate,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="plan_price",
        resource_id=str(price.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return price


def _price_in_effect(
    *, clinic_id: UUID, plan_id: UUID, on_date: date
) -> PlanPrice | None:
    from django.db.models import Q

    return (
        PlanPrice.infrastructure_objects.filter(
            clinic_id=clinic_id,
            plan_id=plan_id,
            is_active=True,
            valid_from__lte=on_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .order_by("-valid_from", "-created_at")
        .first()
    )


@transaction.atomic
def create_subscription(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subscriber_id: UUID,
    plan_id: UUID,
    trial_days: int = 0,
    coupon_code: str = "",
    idempotency_key: str,
    request_id: UUID,
) -> Subscription:
    """Create one subscription idempotently, never persisting card data."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = Subscription.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing
    plan = Plan.infrastructure_objects.filter(pk=plan_id, clinic_id=clinic_id).first()
    if plan is None:
        raise ValidationError("Plano não encontrado.")
    price = _price_in_effect(
        clinic_id=clinic_id, plan_id=plan.pk, on_date=timezone.localdate()
    )
    if price is None:
        raise ValidationError("Não há preço vigente para este plano.")
    today = timezone.localdate()
    period_start = today
    period_end = today + timedelta(days=_interval_days(price.interval))
    trial_ends = today + timedelta(days=trial_days) if trial_days > 0 else None
    status = SubscriptionStatus.TRIALING if trial_ends else SubscriptionStatus.ACTIVE
    subscription = Subscription(
        clinic_id=clinic_id,
        subscriber_id=subscriber_id,
        plan_id=plan.pk,
        status=status,
        current_period_start=period_start,
        current_period_end=period_end,
        trial_ends_at=trial_ends,
        idempotency_key=key,
    )
    subscription.full_clean(validate_unique=False, validate_constraints=False)
    subscription.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="subscription",
        resource_id=str(subscription.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return subscription


@transaction.atomic
def renew_subscription(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subscription_id: UUID,
    request_id: UUID,
) -> Subscription:
    """Advance one active subscription to its next billing period."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    subscription = (
        Subscription.infrastructure_objects.select_for_update()
        .filter(pk=subscription_id, clinic_id=clinic_id)
        .first()
    )
    if subscription is None:
        raise PermissionDenied
    if subscription.status not in {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.TRIALING,
    }:
        raise ValidationError("Somente assinaturas ativas ou em teste podem renovar.")
    price = _price_in_effect(
        clinic_id=clinic_id, plan_id=subscription.plan_id, on_date=timezone.localdate()
    )
    if price is None:
        raise ValidationError("Não há preço vigente para este plano.")
    days = _interval_days(price.interval)
    subscription.current_period_start = subscription.current_period_end
    subscription.current_period_end = subscription.current_period_end + timedelta(
        days=days
    )
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.trial_ends_at = None
    subscription.save(
        update_fields=(
            "current_period_start",
            "current_period_end",
            "status",
            "trial_ends_at",
            "updated_at",
        )
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="subscription",
        resource_id=str(subscription.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return subscription


@transaction.atomic
def pause_subscription(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subscription_id: UUID,
    request_id: UUID,
) -> Subscription:
    """Pause one active subscription."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    subscription = (
        Subscription.infrastructure_objects.select_for_update()
        .filter(pk=subscription_id, clinic_id=clinic_id)
        .first()
    )
    if subscription is None:
        raise PermissionDenied
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise ValidationError("Somente assinaturas ativas podem ser pausadas.")
    subscription.status = SubscriptionStatus.PAUSED
    subscription.save(update_fields=("status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="subscription",
        resource_id=str(subscription.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return subscription


@transaction.atomic
def cancel_subscription(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subscription_id: UUID,
    request_id: UUID,
) -> Subscription:
    """Cancel one subscription, preserving its history."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    subscription = (
        Subscription.infrastructure_objects.select_for_update()
        .filter(pk=subscription_id, clinic_id=clinic_id)
        .first()
    )
    if subscription is None:
        raise PermissionDenied
    if subscription.status == SubscriptionStatus.CANCELED:
        return subscription
    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = timezone.now()
    subscription.save(update_fields=("status", "canceled_at", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="subscription",
        resource_id=str(subscription.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return subscription
