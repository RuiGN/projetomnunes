"""Transactional services for tokenized checkout and idempotent webhooks."""

from __future__ import annotations

import hashlib
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .models import Subscription, SubscriptionStatus
from .payment_adapter import CheckoutResult, PaymentProvider, WebhookPayload
from .webhook_models import WebhookEvent, WebhookStatus

__all__ = [
    "Service",
    "process_webhook_event",
    "tokenize_checkout",
]


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


@transaction.atomic
def tokenize_checkout(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subscription_id: UUID,
    provider: PaymentProvider,
    request_id: UUID,
) -> CheckoutResult:
    """Attach an opaque provider token to one subscription via the adapter.

    No card data is ever persisted; the adapter returns only an opaque token.
    """
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
        SubscriptionStatus.TRIALING,
        SubscriptionStatus.ACTIVE,
    }:
        raise ValidationError(
            "Somente assinaturas ativas ou em teste podem ser tokenizadas."
        )
    result = provider.create_checkout(
        plan_code=subscription.plan.code,
        amount="0.00",
        currency="BRL",
    )
    subscription.provider_token = result.provider_token
    subscription.save(update_fields=("provider_token", "updated_at"))
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
    return result


@transaction.atomic
def process_webhook_event(
    *,
    clinic_id: UUID,
    provider: PaymentProvider,
    payload: WebhookPayload,
    request_id: UUID,
) -> WebhookEvent:
    """Process one provider event idempotently by external event id.

    The payload is sanitized (only a digest is persisted) and the event is
    deduplicated so a repeated webhook never applies twice.
    """
    lock_clinic_for_update(clinic_id=clinic_id)
    digest = hashlib.sha256(
        f"{payload.event_type}:{payload.provider_token}:{payload.status}".encode()
    ).hexdigest()
    existing = WebhookEvent.infrastructure_objects.filter(
        clinic_id=clinic_id, external_event_id=payload.event_id
    ).first()
    if existing is not None:
        existing.status = WebhookStatus.DUPLICATE
        existing.save(update_fields=("status", "updated_at"))
        return existing

    normalized_status = provider.process_webhook(payload=payload)
    event = WebhookEvent(
        clinic_id=clinic_id,
        external_event_id=payload.event_id,
        event_type=payload.event_type,
        provider_token=payload.provider_token,
        status=WebhookStatus.PROCESSED,
        payload_digest=digest,
    )
    event.full_clean(validate_unique=False, validate_constraints=False)
    event.save(force_insert=True)

    subscription = Subscription.infrastructure_objects.filter(
        clinic_id=clinic_id, provider_token=payload.provider_token
    ).first()
    if subscription is not None and normalized_status == "canceled":
        subscription.status = SubscriptionStatus.CANCELED
        subscription.save(update_fields=("status", "updated_at"))

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=None,
        action="update",
        resource_type="webhook_event",
        resource_id=str(event.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return event
