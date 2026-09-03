"""Transactional services for service prices and accounts receivable."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service
from scheduling.selectors import (
    AppointmentStatus,
    appointment_for_finance,
)

from .events import charge_canceled, charge_generated, charge_settled
from .models import Charge, ChargeStatus, ServicePrice

__all__ = [
    "Service",
    "cancel_charge",
    "generate_charge_for_appointment",
    "set_service_price",
    "settle_charge",
]

DEFAULT_DUE_DAYS = 7


def _require_finance_role(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    today = timezone.localdate()
    if not (
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=today
        )
        or has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=actor.pk,
            role="administrative_staff",
            on_date=today,
        )
    ):
        raise PermissionDenied


@transaction.atomic
def set_service_price(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    service_id: UUID,
    amount: Decimal,
    currency: str,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> ServicePrice:
    """Create one effective price for a service, preserving prior versions."""
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    lock_clinic_for_update(clinic_id=clinic_id)
    if amount < 0:
        raise ValidationError("O valor não pode ser negativo.")
    if valid_until is not None and valid_until < valid_from:
        raise ValidationError("A data final não pode ser anterior à inicial.")
    price = ServicePrice.infrastructure_objects.create(
        clinic_id=clinic_id,
        service_id=service_id,
        amount=amount,
        currency=currency.upper(),
        valid_from=valid_from,
        valid_until=valid_until,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="service_price",
        resource_id=str(price.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return price


def _price_in_effect(
    *, clinic_id: UUID, service_id: UUID, on_date: date
) -> ServicePrice | None:
    from django.db.models import Q

    return (
        ServicePrice.infrastructure_objects.filter(
            clinic_id=clinic_id,
            service_id=service_id,
            is_active=True,
            valid_from__lte=on_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .order_by("-valid_from", "-created_at")
        .first()
    )


@transaction.atomic
def generate_charge_for_appointment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    due_date: date | None = None,
    request_id: UUID,
) -> Charge:
    """Generate one idempotent charge from a confirmed appointment.

    The price in effect at generation time is captured; later price changes
    never mutate an existing charge.
    """
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    appointment = appointment_for_finance(
        clinic_id=clinic_id, appointment_id=appointment_id
    )
    if appointment is None:
        raise PermissionDenied
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise ValidationError("Somente consultas confirmadas geram cobrança.")

    idempotency_key = f"appointment:{appointment.pk}"
    existing = Charge.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        return existing

    price = _price_in_effect(
        clinic_id=clinic_id,
        service_id=appointment.service_id,
        on_date=timezone.localdate(),
    )
    if price is None:
        raise ValidationError("Não há preço vigente para este serviço.")

    effective_due = due_date or (
        timezone.localdate() + timedelta(days=DEFAULT_DUE_DAYS)
    )
    charge = Charge(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        service_id=appointment.service_id,
        amount=price.amount,
        currency=price.currency,
        due_date=effective_due,
        status=ChargeStatus.OPEN,
        idempotency_key=idempotency_key,
    )
    charge.full_clean(validate_unique=False, validate_constraints=False)
    charge.save(force_insert=True)
    charge_generated.send(
        sender=Charge,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(charge.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="charge",
        resource_id=str(charge.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return charge


@transaction.atomic
def settle_charge(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    charge_id: UUID,
    request_id: UUID,
) -> Charge:
    """Record a manual payment for one open or overdue charge."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    charge = (
        Charge.infrastructure_objects.select_for_update()
        .filter(pk=charge_id, clinic_id=clinic_id)
        .first()
    )
    if charge is None:
        raise PermissionDenied
    if charge.status not in {ChargeStatus.OPEN, ChargeStatus.OVERDUE}:
        raise ValidationError(
            "Somente cobranças em aberto ou vencidas podem ser baixadas."
        )
    charge.status = ChargeStatus.PAID
    charge.settled_at = timezone.now()
    charge.settled_by_id = actor.pk
    charge.save(update_fields=("status", "settled_at", "settled_by", "updated_at"))
    charge_settled.send(
        sender=Charge,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(charge.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="charge",
        resource_id=str(charge.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return charge


@transaction.atomic
def cancel_charge(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    charge_id: UUID,
    reason: str,
    request_id: UUID,
) -> Charge:
    """Cancel one open or overdue charge with a recorded reason."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    charge = (
        Charge.infrastructure_objects.select_for_update()
        .filter(pk=charge_id, clinic_id=clinic_id)
        .first()
    )
    if charge is None:
        raise PermissionDenied
    if charge.status not in {ChargeStatus.OPEN, ChargeStatus.OVERDUE}:
        raise ValidationError(
            "Somente cobranças em aberto ou vencidas podem ser canceladas."
        )
    charge.status = ChargeStatus.CANCELED
    charge.canceled_at = timezone.now()
    charge.canceled_by_id = actor.pk
    charge.cancel_reason = reason.strip()
    charge.save(
        update_fields=(
            "status",
            "canceled_at",
            "canceled_by",
            "cancel_reason",
            "updated_at",
        )
    )
    charge_canceled.send(
        sender=Charge,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(charge.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="charge",
        resource_id=str(charge.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return charge
