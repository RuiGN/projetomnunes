"""Acceptance tests for PRD 8.11.1 — catálogo, assinaturas e ciclo de cobrança."""

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
from finance.models import (
    BillingInterval,
    Plan,
    PlanPrice,
    Subscription,
    SubscriptionStatus,
)
from finance.subscription_services import (
    cancel_subscription,
    create_plan,
    create_plan_price,
    create_subscription,
    pause_subscription,
    renew_subscription,
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


def _plan(clinic: Clinic, admin: User, code: str = "basico") -> Plan:
    return create_plan(
        clinic_id=clinic.pk,
        actor=admin,
        code=code,
        name="Plano Básico",
        description="",
        request_id=uuid4(),
    )


def _price(clinic: Clinic, admin: User, plan: Plan, amount: str = "99.90") -> PlanPrice:
    return create_plan_price(
        clinic_id=clinic.pk,
        actor=admin,
        plan_id=plan.pk,
        amount=Decimal(amount),
        currency="BRL",
        interval=BillingInterval.MONTHLY,
        tax_rate=Decimal("0.0"),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# 8.11.1.1 — plan and price catalog
# ---------------------------------------------------------------------------


def test_create_plan_versions_increment() -> None:
    clinic, admin = _admin()
    first = _plan(clinic, admin, "basico")
    second = _plan(clinic, admin, "basico")
    assert first.version == 1
    assert second.version == 2


def test_create_plan_requires_admin() -> None:
    clinic, _ignored = _admin()
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        create_plan(
            clinic_id=clinic.pk,
            actor=outsider,
            code="basico",
            name="Plano",
            description="",
            request_id=uuid4(),
        )


def test_create_plan_price_rejects_negative() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    with pytest.raises(ValidationError):
        create_plan_price(
            clinic_id=clinic.pk,
            actor=admin,
            plan_id=plan.pk,
            amount=Decimal("-1.00"),
            currency="BRL",
            interval=BillingInterval.MONTHLY,
            tax_rate=Decimal("0.0"),
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.1.2 — subscription lifecycle with proportional periods
# ---------------------------------------------------------------------------


def test_create_subscription_is_idempotent() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    _price(clinic, admin, plan)
    subscriber = UserFactory.create()
    key = uuid4().hex

    first = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=key,
        request_id=uuid4(),
    )
    second = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=key,
        request_id=uuid4(),
    )

    assert first.pk == second.pk
    assert Subscription.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 1


def test_create_subscription_with_trial() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    _price(clinic, admin, plan)
    subscriber = UserFactory.create()

    subscription = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        trial_days=14,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )

    assert subscription.status == SubscriptionStatus.TRIALING
    assert subscription.trial_ends_at == timezone.localdate() + timedelta(days=14)


def test_create_subscription_requires_price() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    subscriber = UserFactory.create()
    with pytest.raises(ValidationError):
        create_subscription(
            clinic_id=clinic.pk,
            actor=admin,
            subscriber_id=subscriber.pk,
            plan_id=plan.pk,
            idempotency_key=uuid4().hex,
            request_id=uuid4(),
        )


def test_renew_subscription_advances_period() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    _price(clinic, admin, plan)
    subscriber = UserFactory.create()
    subscription = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    original_end = subscription.current_period_end

    renewed = renew_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        request_id=uuid4(),
    )

    assert renewed.current_period_start == original_end
    assert renewed.current_period_end == original_end + timedelta(days=30)
    assert renewed.status == SubscriptionStatus.ACTIVE


def test_pause_and_cancel_subscription() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    _price(clinic, admin, plan)
    subscriber = UserFactory.create()
    subscription = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )

    paused = pause_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        request_id=uuid4(),
    )
    assert paused.status == SubscriptionStatus.PAUSED

    canceled = cancel_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        request_id=uuid4(),
    )
    assert canceled.status == SubscriptionStatus.CANCELED
    assert canceled.canceled_at is not None


def test_subscription_cross_clinic_denied() -> None:
    clinic_a, admin_a = _admin()
    clinic_b, admin_b = _admin()
    plan = _plan(clinic_a, admin_a)
    _price(clinic_a, admin_a, plan)
    subscriber = UserFactory.create()
    subscription = create_subscription(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        cancel_subscription(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            subscription_id=subscription.pk,
            request_id=uuid4(),
        )


def test_subscription_audits() -> None:
    clinic, admin = _admin()
    plan = _plan(clinic, admin)
    _price(clinic, admin, plan)
    subscriber = UserFactory.create()
    subscription = create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            action="create",
            resource_type="subscription",
            resource_id=str(subscription.pk),
        )
        .exists()
    )
