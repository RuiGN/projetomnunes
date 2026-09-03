"""Acceptance tests for PRD 8.11.1.2/8.11.1.3 — checkout tokenizado e webhooks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from finance.models import (
    BillingInterval,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    WebhookStatus,
)
from finance.payment_adapter import (
    FakePaymentProvider,
    FlakyPaymentProvider,
    WebhookPayload,
)
from finance.subscription_services import (
    create_plan,
    create_plan_price,
    create_subscription,
)
from finance.webhook_services import process_webhook_event, tokenize_checkout
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def _subscription(clinic: Clinic, admin: User) -> Subscription:
    plan = create_plan(
        clinic_id=clinic.pk,
        actor=admin,
        code="basico",
        name="Plano",
        description="",
        request_id=uuid4(),
    )
    create_plan_price(
        clinic_id=clinic.pk,
        actor=admin,
        plan_id=plan.pk,
        amount=Decimal("99.90"),
        currency="BRL",
        interval=BillingInterval.MONTHLY,
        tax_rate=Decimal("0.0"),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    subscriber = UserFactory.create()
    return create_subscription(
        clinic_id=clinic.pk,
        actor=admin,
        subscriber_id=subscriber.pk,
        plan_id=plan.pk,
        idempotency_key=uuid4().hex,
        request_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# 8.11.1.2 — tokenized checkout
# ---------------------------------------------------------------------------


def test_tokenize_checkout_attaches_opaque_token() -> None:
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FakePaymentProvider()

    result = tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )

    assert result.provider_token.startswith("tok_")
    subscription.refresh_from_db()
    assert subscription.provider_token == result.provider_token


def test_tokenize_checkout_never_persists_card_data() -> None:
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FakePaymentProvider()

    tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )

    subscription.refresh_from_db()
    assert "pan" not in subscription.provider_token
    assert "cvv" not in subscription.provider_token


def test_tokenize_checkout_requires_admin() -> None:
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        tokenize_checkout(
            clinic_id=clinic.pk,
            actor=outsider,
            subscription_id=subscription.pk,
            provider=FakePaymentProvider(),
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.11.1.3 — idempotent webhook processing
# ---------------------------------------------------------------------------


def _payload(
    token: str, event_id: str = "evt_1", status: str = "active"
) -> WebhookPayload:
    return WebhookPayload(
        event_id=event_id,
        event_type="subscription.updated",
        provider_token=token,
        status=status,
        raw_signature="sig",
    )


def test_process_webhook_is_idempotent() -> None:
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FakePaymentProvider()
    tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )
    subscription.refresh_from_db()
    payload = _payload(subscription.provider_token)

    first = process_webhook_event(
        clinic_id=clinic.pk, provider=provider, payload=payload, request_id=uuid4()
    )
    second = process_webhook_event(
        clinic_id=clinic.pk, provider=provider, payload=payload, request_id=uuid4()
    )

    assert first.status == WebhookStatus.PROCESSED
    assert second.status == WebhookStatus.DUPLICATE
    assert WebhookEvent.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 1


def test_process_webhook_cancels_subscription() -> None:
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FakePaymentProvider()
    tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )
    subscription.refresh_from_db()

    process_webhook_event(
        clinic_id=clinic.pk,
        provider=provider,
        payload=_payload(
            subscription.provider_token, event_id="evt_cancel", status="canceled"
        ),
        request_id=uuid4(),
    )

    subscription.refresh_from_db()
    assert subscription.status == SubscriptionStatus.CANCELED


def test_process_webhook_unknown_token() -> None:
    clinic, _ignored = _admin()
    provider = FakePaymentProvider()
    event = process_webhook_event(
        clinic_id=clinic.pk,
        provider=provider,
        payload=_payload("tok_unknown", event_id="evt_unknown"),
        request_id=uuid4(),
    )
    assert event.status == WebhookStatus.PROCESSED
    assert event.provider_token == "tok_unknown"


# ---------------------------------------------------------------------------
# 8.11.1.4 — retry and resume after provider failure
# ---------------------------------------------------------------------------


def test_checkout_resumes_after_transient_provider_failure() -> None:
    """8.11.1.4: a transient provider timeout does not corrupt the subscription."""
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FlakyPaymentProvider(failures=1)

    with pytest.raises(TimeoutError):
        tokenize_checkout(
            clinic_id=clinic.pk,
            actor=admin,
            subscription_id=subscription.pk,
            provider=provider,
            request_id=uuid4(),
        )

    # The subscription is unchanged after the failed attempt.
    subscription.refresh_from_db()
    assert subscription.provider_token == ""

    # A retry with the same provider succeeds and attaches the token.
    result = tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )
    subscription.refresh_from_db()
    assert subscription.provider_token == result.provider_token


def test_repeated_webhook_never_duplicates() -> None:
    """8.11.1.4: a repeated webhook is deduplicated, not applied twice."""
    clinic, admin = _admin()
    subscription = _subscription(clinic, admin)
    provider = FakePaymentProvider()
    tokenize_checkout(
        clinic_id=clinic.pk,
        actor=admin,
        subscription_id=subscription.pk,
        provider=provider,
        request_id=uuid4(),
    )
    subscription.refresh_from_db()
    payload = _payload(
        subscription.provider_token, event_id="evt_retry", status="canceled"
    )

    process_webhook_event(
        clinic_id=clinic.pk, provider=provider, payload=payload, request_id=uuid4()
    )
    process_webhook_event(
        clinic_id=clinic.pk, provider=provider, payload=payload, request_id=uuid4()
    )

    assert WebhookEvent.infrastructure_objects.filter(clinic_id=clinic.pk).count() == 1
    subscription.refresh_from_db()
    assert subscription.status == SubscriptionStatus.CANCELED
