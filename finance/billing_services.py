"""Transactional services for ad-hoc charges, refunds and the exception queue."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.services import lock_clinic_for_update
from core.services import Service as Service

from .billing_models import (
    AdHocCharge,
    ExceptionQueueItem,
    RefundKind,
    RefundRequest,
    RefundStatus,
)
from .models import Charge, ChargeStatus

__all__ = [
    "Service",
    "approve_refund",
    "create_ad_hoc_charge",
    "enqueue_exception",
    "mark_overdue_charges",
    "reject_refund",
    "request_refund",
    "resolve_exception",
]


def _require_finance_role(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    from clinics.policies import has_active_clinic_role

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
def create_ad_hoc_charge(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    appointment_id: UUID,
    description: str,
    amount: Decimal,
    currency: str,
    due_date: date,
    idempotency_key: str,
    request_id: UUID,
) -> AdHocCharge:
    """Create one standalone charge, validating amount, currency and beneficiary."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    from scheduling.selectors import appointment_for_finance

    lock_clinic_for_update(clinic_id=clinic_id)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = AdHocCharge.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing
    appointment = appointment_for_finance(
        clinic_id=clinic_id, appointment_id=appointment_id
    )
    if appointment is None:
        raise PermissionDenied
    if amount < 0:
        raise ValidationError("O valor não pode ser negativo.")
    charge = AdHocCharge.infrastructure_objects.create(
        clinic_id=clinic_id,
        appointment_id=appointment.pk,
        description=description.strip(),
        amount=amount,
        currency=currency.upper(),
        due_date=due_date,
        idempotency_key=key,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="ad_hoc_charge",
        resource_id=str(charge.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return charge


@transaction.atomic
def mark_overdue_charges(
    *, clinic_id: UUID, request_id: UUID, actor: AbstractBaseUser
) -> int:
    """Flip open charges past their due date to overdue (régua de inadimplência)."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    today = timezone.localdate()
    overdue = Charge.infrastructure_objects.select_for_update().filter(
        clinic_id=clinic_id,
        status=ChargeStatus.OPEN,
        due_date__lt=today,
    )
    count = 0
    for charge in overdue:
        charge.status = ChargeStatus.OVERDUE
        charge.save(update_fields=("status", "updated_at"))
        count += 1
    adhoc = AdHocCharge.infrastructure_objects.select_for_update().filter(
        clinic_id=clinic_id, status="open", due_date__lt=today
    )
    for ad_hoc in adhoc:
        ad_hoc.status = "overdue"
        ad_hoc.save(update_fields=("status", "updated_at"))
        count += 1
    if count:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor.pk,
            action="update",
            resource_type="charge_overdue_batch",
            resource_id=str(clinic_id),
            outcome="success",
            request_id=request_id,
            network_origin=None,
        )
    return count


@transaction.atomic
def request_refund(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    charge_id: UUID,
    kind: str,
    amount: Decimal,
    justification: str,
    idempotency_key: str,
    request_id: UUID,
) -> RefundRequest:
    """Create one refund/chargeback request with a mandatory justification."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = RefundRequest.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing
    charge = Charge.infrastructure_objects.filter(
        pk=charge_id, clinic_id=clinic_id
    ).first()
    if charge is None:
        raise PermissionDenied
    if charge.status != ChargeStatus.PAID:
        raise ValidationError("Somente cobranças pagas podem ser reembolsadas.")
    if not justification.strip():
        raise ValidationError("A justificativa é obrigatória.")
    if kind not in RefundKind.values:
        raise ValidationError("Tipo de reembolso inválido.")
    if amount <= 0 or amount > charge.net_amount:
        raise ValidationError("O valor deve ser positivo e não exceder a cobrança.")
    refund = RefundRequest.infrastructure_objects.create(
        clinic_id=clinic_id,
        charge_id=charge.pk,
        kind=kind,
        amount=amount,
        justification=justification.strip(),
        requested_by_id=actor.pk,
        idempotency_key=key,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="refund_request",
        resource_id=str(refund.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return refund


@transaction.atomic
def approve_refund(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    refund_id: UUID,
    request_id: UUID,
) -> RefundRequest:
    """Approve one pending refund request, reducing the charge balance."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    refund = (
        RefundRequest.infrastructure_objects.select_for_update()
        .filter(pk=refund_id, clinic_id=clinic_id)
        .first()
    )
    if refund is None:
        raise PermissionDenied
    if refund.status != RefundStatus.PENDING:
        raise ValidationError("Somente pedidos pendentes podem ser aprovados.")
    refund.status = RefundStatus.APPROVED
    refund.decided_by_id = actor.pk
    refund.save(update_fields=("status", "decided_by", "updated_at"))
    charge = (
        Charge.infrastructure_objects.select_for_update()
        .filter(pk=refund.charge_id, clinic_id=clinic_id)
        .first()
    )
    if charge is not None and refund.amount >= charge.net_amount:
        charge.status = ChargeStatus.CANCELED
        charge.save(update_fields=("status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="refund_request",
        resource_id=str(refund.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return refund


@transaction.atomic
def reject_refund(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    refund_id: UUID,
    request_id: UUID,
) -> RefundRequest:
    """Reject one pending refund request with a recorded decider."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    refund = (
        RefundRequest.infrastructure_objects.select_for_update()
        .filter(pk=refund_id, clinic_id=clinic_id)
        .first()
    )
    if refund is None:
        raise PermissionDenied
    if refund.status != RefundStatus.PENDING:
        raise ValidationError("Somente pedidos pendentes podem ser recusados.")
    refund.status = RefundStatus.REJECTED
    refund.decided_by_id = actor.pk
    refund.save(update_fields=("status", "decided_by", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="refund_request",
        resource_id=str(refund.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return refund


def enqueue_exception(
    *,
    clinic_id: UUID,
    kind: str,
    reference: str = "",
    detail: dict[str, object] | None = None,
) -> ExceptionQueueItem:
    """Queue one finance exception for later idempotent reprocessing."""
    return ExceptionQueueItem.infrastructure_objects.create(
        clinic_id=clinic_id,
        kind=kind,
        reference=reference,
        detail=detail or {},
    )


@transaction.atomic
def resolve_exception(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    item_id: UUID,
    request_id: UUID,
) -> ExceptionQueueItem:
    """Mark one exception item as resolved with its resolver recorded."""
    _require_finance_role(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    item = (
        ExceptionQueueItem.infrastructure_objects.select_for_update()
        .filter(pk=item_id, clinic_id=clinic_id)
        .first()
    )
    if item is None:
        raise PermissionDenied
    if item.status == "resolved":
        return item
    item.status = "resolved"
    item.resolved_by_id = actor.pk
    item.save(update_fields=("status", "resolved_by", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="exception_queue_item",
        resource_id=str(item.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return item
