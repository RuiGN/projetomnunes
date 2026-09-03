"""Financial dashboards and protected CSV export services."""

from __future__ import annotations

import csv
import io
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from core.services import Service as Service

from .billing_models import AdHocCharge, RefundRequest, RefundStatus
from .models import Charge, ChargeStatus
from .payout_models import FiscalDocument, PayoutBatch
from .storage import PrivateFinanceStorage

__all__ = [
    "Service",
    "ExportHandle",
    "FinancialDashboardData",
    "authorize_export_download",
    "export_financial_csv",
    "financial_dashboard",
]

EXPORT_TTL_HOURS = 24
_EXPORTS: dict[UUID, dict[str, Any]] = {}


@dataclass(frozen=True, slots=True)
class FinancialDashboardData:
    """Aggregated financial view derived from reconcilable records."""

    period_start: date
    period_end: date
    gross_revenue: Decimal
    net_revenue: Decimal
    receivable_open: Decimal
    receivable_overdue: Decimal
    refunded: Decimal
    payout_settled: Decimal
    fiscal_issued: int
    last_updated: datetime


@dataclass(frozen=True, slots=True)
class ExportHandle:
    """One protected export artifact with an expiring download key."""

    export_id: UUID
    download_key: str
    expires_at: datetime


def _finance_actor(*, clinic_id: UUID, actor: AbstractBaseUser) -> bool:
    today = timezone.localdate()
    return has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=today
    )


def _bounds(period_start: date, period_end: date) -> tuple[date, date]:
    if period_end < period_start:
        raise ValidationError("O período final deve ser igual ou posterior ao inicial.")
    return period_start, period_end


def financial_dashboard(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
) -> FinancialDashboardData:
    """Aggregate finance metrics for one clinic and period (admin only)."""
    if not _finance_actor(clinic_id=clinic_id, actor=actor):
        raise PermissionDenied
    start, end = _bounds(period_start, period_end)

    gross = Decimal("0.00")
    net = Decimal("0.00")
    open_amount = Decimal("0.00")
    overdue_amount = Decimal("0.00")
    for charge in Charge.infrastructure_objects.filter(
        clinic_id=clinic_id,
        due_date__gte=start,
        due_date__lte=end,
    ):
        if charge.status == ChargeStatus.PAID:
            gross += charge.amount
            net += charge.net_amount
        elif charge.status == ChargeStatus.OPEN:
            open_amount += charge.net_amount
        elif charge.status == ChargeStatus.OVERDUE:
            overdue_amount += charge.net_amount

    for adhoc_charge in AdHocCharge.infrastructure_objects.filter(
        clinic_id=clinic_id,
        due_date__gte=start,
        due_date__lte=end,
        status="paid",
    ):
        gross += adhoc_charge.amount
        net += adhoc_charge.amount

    refunded = Decimal("0.00")
    for refund in RefundRequest.infrastructure_objects.filter(
        clinic_id=clinic_id,
        status=RefundStatus.APPROVED,
        charge__due_date__gte=start,
        charge__due_date__lte=end,
    ):
        refunded += refund.amount

    payout_settled = Decimal("0.00")
    for batch in PayoutBatch.infrastructure_objects.filter(
        clinic_id=clinic_id, status=PayoutBatch.Status.SETTLED
    ):
        payout_settled += batch.total_amount

    fiscal_issued = FiscalDocument.infrastructure_objects.filter(
        clinic_id=clinic_id,
        status=FiscalDocument.Status.ISSUED,
        competence_date__gte=start,
        competence_date__lte=end,
    ).count()

    return FinancialDashboardData(
        period_start=period_start,
        period_end=period_end,
        gross_revenue=gross,
        net_revenue=net,
        receivable_open=open_amount,
        receivable_overdue=overdue_amount,
        refunded=refunded,
        payout_settled=payout_settled,
        fiscal_issued=fiscal_issued,
        last_updated=timezone.now(),
    )


class _Bytes(io.BytesIO):
    """A BytesIO with a size() method so Django storage accepts it."""

    def size(self) -> int:
        return len(self.getvalue())


def _dashboard_csv(data: FinancialDashboardData) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("metric", "value", "currency"))
    writer.writerow(("gross_revenue", str(data.gross_revenue), "BRL"))
    writer.writerow(("net_revenue", str(data.net_revenue), "BRL"))
    writer.writerow(("receivable_open", str(data.receivable_open), "BRL"))
    writer.writerow(("receivable_overdue", str(data.receivable_overdue), "BRL"))
    writer.writerow(("refunded", str(data.refunded), "BRL"))
    writer.writerow(("payout_settled", str(data.payout_settled), "BRL"))
    writer.writerow(("fiscal_issued", str(data.fiscal_issued), ""))
    writer.writerow(
        (
            "period",
            f"{data.period_start.isoformat()}..{data.period_end.isoformat()}",
            "",
        )
    )
    return output.getvalue()


@transaction.atomic
def export_financial_csv(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period_start: date,
    period_end: date,
    request_id: UUID,
) -> ExportHandle:
    """Export the finance dashboard as CSV behind an expiring key (admin only)."""
    data = financial_dashboard(
        clinic_id=clinic_id,
        actor=actor,
        period_start=period_start,
        period_end=period_end,
    )
    content = _dashboard_csv(data)
    export_id = uuid4()
    download_key = secrets.token_hex(16)
    storage = PrivateFinanceStorage()
    path = storage.save(
        f"finance/{clinic_id}/exports/{export_id.hex}.csv",
        _Bytes(content.encode("utf-8")),
    )
    _EXPORTS[export_id] = {
        "clinic_id": clinic_id,
        "actor_id": actor.pk,
        "download_key": download_key,
        "path": str(path),
        "expires_at": timezone.now() + timedelta(hours=EXPORT_TTL_HOURS),
    }
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="export",
        resource_type="finance_export",
        resource_id=str(export_id),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return ExportHandle(
        export_id=export_id,
        download_key=download_key,
        expires_at=_EXPORTS[export_id]["expires_at"],
    )


def authorize_export_download(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    export_id: UUID,
    download_key: str,
    request_id: UUID,
) -> str:
    """Return the CSV content when key, actor and expiry all match."""
    record = _EXPORTS.get(export_id)
    if (
        record is None
        or record["clinic_id"] != clinic_id
        or record["actor_id"] != actor.pk
        or record["download_key"] != download_key
        or timezone.now() > record["expires_at"]
    ):
        raise PermissionDenied
    if not _finance_actor(clinic_id=clinic_id, actor=actor):
        raise PermissionDenied
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="view",
        resource_type="finance_export",
        resource_id=str(export_id),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    storage = PrivateFinanceStorage()
    with storage.open(str(record["path"])) as handle:
        payload = handle.read()
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        return str(payload)
