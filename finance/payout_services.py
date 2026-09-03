"""Transactional services for payouts, commissions and fiscal documents."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import Service as Service

from .billing_models import AdHocCharge
from .ledger_services import post_double_entry
from .models import Charge, ChargeStatus
from .payout_models import (
    FiscalDocument,
    PayoutBatch,
    PayoutRule,
)

__all__ = [
    "Service",
    "approve_payout_batch",
    "cancel_fiscal_document",
    "create_payout_batch",
    "create_payout_rule",
    "issue_fiscal_document",
    "settle_payout_batch",
]

CENT = Decimal("0.01")


def _require_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


def _round(value: Decimal) -> Decimal:
    """Apply deterministic banker-safe rounding to the cent."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _rate_in_effect(
    *, clinic_id: UUID, professional_id: UUID, service_id: UUID, on_date: date
) -> PayoutRule | None:
    from django.db.models import Q

    valid = Q(valid_until__isnull=True) | Q(valid_until__gte=on_date)
    specific = (
        PayoutRule.infrastructure_objects.filter(
            clinic_id=clinic_id,
            is_active=True,
            valid_from__lte=on_date,
            professional_id=professional_id,
            service_id=service_id,
        )
        .filter(valid)
        .order_by("-version", "-created_at")
        .first()
    )
    if specific is not None:
        return specific
    return (
        PayoutRule.infrastructure_objects.filter(
            clinic_id=clinic_id,
            is_active=True,
            valid_from__lte=on_date,
            professional_id=professional_id,
            service_id__isnull=True,
        )
        .filter(valid)
        .order_by("-version", "-created_at")
        .first()
    )


@transaction.atomic
def create_payout_rule(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    professional_id: UUID | None,
    service_id: UUID | None,
    percent_rate: Decimal,
    fixed_amount: Decimal,
    retention_rate: Decimal,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> PayoutRule:
    """Create one versioned payout rule with deterministic rounding inputs."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    if not Decimal("0") <= percent_rate <= Decimal("1"):
        raise ValidationError("A taxa percentual deve estar entre 0 e 1.")
    if fixed_amount < 0 or retention_rate < 0 or retention_rate > 1:
        raise ValidationError("Valores de repasse inválidos.")
    if service_id is not None:
        latest = (
            PayoutRule.infrastructure_objects.filter(
                clinic_id=clinic_id,
                professional_id=professional_id,
                service_id=service_id,
            )
            .order_by("-version")
            .first()
        )
    else:
        latest = (
            PayoutRule.infrastructure_objects.filter(
                clinic_id=clinic_id,
                professional_id=professional_id,
                service_id__isnull=True,
            )
            .order_by("-version")
            .first()
        )
    version = (latest.version + 1) if latest is not None else 1
    rule = PayoutRule.infrastructure_objects.create(
        clinic_id=clinic_id,
        professional_id=professional_id,
        service_id=service_id,
        version=version,
        percent_rate=percent_rate,
        fixed_amount=_round(fixed_amount),
        retention_rate=retention_rate,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="payout_rule",
        resource_id=str(rule.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return rule


@transaction.atomic
def create_payout_batch(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    professional_id: UUID,
    charges: list[UUID],
    idempotency_key: str,
    request_id: UUID,
) -> PayoutBatch:
    """Build one payout batch with item-by-item calculation memory.

    Each paid charge contributes percent_rate minus retention; the batch is
    blocked from settlement until an administrator approves it.
    """
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = PayoutBatch.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing
    today = timezone.localdate()
    memory: list[dict[str, object]] = []
    total = Decimal("0.00")
    for charge_id in charges:
        charge: Charge | AdHocCharge | None = Charge.infrastructure_objects.filter(
            pk=charge_id, clinic_id=clinic_id
        ).first()
        if charge is None:
            charge = AdHocCharge.infrastructure_objects.filter(
                pk=charge_id, clinic_id=clinic_id
            ).first()
        if charge is None:
            raise ValidationError("Cobrança não encontrada.")
        if getattr(charge, "status", "") != ChargeStatus.PAID:
            raise ValidationError("Somente cobranças pagas podem gerar repasse.")
        amount = getattr(charge, "net_amount", None) or charge.amount
        if isinstance(charge, Charge):
            charge_service_id: UUID = charge.service_id
        else:
            charge_service_id = charge.appointment.service_id
        rule = _rate_in_effect(
            clinic_id=clinic_id,
            professional_id=professional_id,
            service_id=charge_service_id,
            on_date=today,
        )
        if rule is None:
            raise ValidationError("Não há regra de repasse vigente para este serviço.")
        gross = _round(amount * rule.percent_rate)
        retention = _round(gross * rule.retention_rate)
        net = _round(gross - retention + rule.fixed_amount)
        memory.append(
            {
                "charge_id": str(charge.pk),
                "amount": str(amount),
                "percent_rate": str(rule.percent_rate),
                "retention_rate": str(rule.retention_rate),
                "fixed_amount": str(rule.fixed_amount),
                "gross": str(gross),
                "retention": str(retention),
                "net": str(net),
            }
        )
        total += net
    batch = PayoutBatch(
        clinic_id=clinic_id,
        professional_id=professional_id,
        total_amount=_round(total),
        calculation_memory=memory,
        idempotency_key=key,
    )
    batch.full_clean(validate_unique=False, validate_constraints=False)
    batch.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="payout_batch",
        resource_id=str(batch.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return batch


@transaction.atomic
def approve_payout_batch(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    batch_id: UUID,
    request_id: UUID,
) -> PayoutBatch:
    """Approve one draft payout batch, unlocking settlement."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    batch = (
        PayoutBatch.infrastructure_objects.select_for_update()
        .filter(pk=batch_id, clinic_id=clinic_id)
        .first()
    )
    if batch is None:
        raise PermissionDenied
    if batch.status != PayoutBatch.Status.DRAFT:
        raise ValidationError("Somente lotes em rascunho podem ser aprovados.")
    batch.status = PayoutBatch.Status.APPROVED
    batch.approved_by_id = actor.pk
    batch.save(update_fields=("status", "approved_by", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="payout_batch",
        resource_id=str(batch.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return batch


@transaction.atomic
def settle_payout_batch(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    batch_id: UUID,
    request_id: UUID,
) -> PayoutBatch:
    """Settle one approved batch by posting its payout to the ledger."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    batch = (
        PayoutBatch.infrastructure_objects.select_for_update()
        .filter(pk=batch_id, clinic_id=clinic_id)
        .first()
    )
    if batch is None:
        raise PermissionDenied
    if batch.status != PayoutBatch.Status.APPROVED:
        raise ValidationError("Somente lotes aprovados podem ser liquidados.")
    post_double_entry(
        clinic_id=clinic_id,
        actor=actor,
        debit_account_code="5.2.001",
        credit_account_code="1.1.001",
        amount=batch.total_amount,
        currency=batch.currency,
        source_type="payout_batch",
        source_id=batch.pk,
        request_id=request_id,
    )
    batch.status = PayoutBatch.Status.SETTLED
    batch.settled_at = timezone.now()
    batch.save(update_fields=("status", "settled_at", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="payout_batch",
        resource_id=str(batch.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return batch


@transaction.atomic
def issue_fiscal_document(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    charge_id: UUID,
    document_type: str,
    idempotency_key: str,
    request_id: UUID,
) -> FiscalDocument:
    """Issue one invoice or receipt idempotently for a paid charge."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    key = idempotency_key.strip()
    if not key:
        raise ValidationError("Chave de idempotência é obrigatória.")
    existing = FiscalDocument.infrastructure_objects.filter(
        clinic_id=clinic_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing
    if document_type not in {"invoice", "receipt"}:
        raise ValidationError("Tipo de documento inválido.")
    charge = (
        Charge.infrastructure_objects.filter(pk=charge_id, clinic_id=clinic_id).first()
        or AdHocCharge.infrastructure_objects.filter(
            pk=charge_id, clinic_id=clinic_id
        ).first()
    )
    if charge is None:
        raise PermissionDenied
    if (
        document_type == "invoice"
        and getattr(charge, "status", "") != ChargeStatus.PAID
    ):
        raise ValidationError("Somente cobranças pagas podem emitir nota fiscal.")
    document = FiscalDocument(
        clinic_id=clinic_id,
        charge_id=charge.pk,
        document_type=document_type,
        status=FiscalDocument.Status.ISSUED,
        document_number=f"DOC-{uuid4().hex[:12].upper()}",
        competence_date=timezone.localdate(),
        amount=getattr(charge, "net_amount", None) or charge.amount,
        idempotency_key=key,
    )
    document.full_clean(validate_unique=False, validate_constraints=False)
    document.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="fiscal_document",
        resource_id=str(document.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return document


@transaction.atomic
def cancel_fiscal_document(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    document_id: UUID,
    request_id: UUID,
) -> FiscalDocument:
    """Cancel one issued fiscal document with an audit trail."""
    _require_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    document = (
        FiscalDocument.infrastructure_objects.select_for_update()
        .filter(pk=document_id, clinic_id=clinic_id)
        .first()
    )
    if document is None:
        raise PermissionDenied
    if document.status != FiscalDocument.Status.ISSUED:
        raise ValidationError("Somente documentos emitidos podem ser cancelados.")
    document.status = FiscalDocument.Status.CANCELED
    document.save(update_fields=("status", "updated_at"))
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="fiscal_document",
        resource_id=str(document.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return document
