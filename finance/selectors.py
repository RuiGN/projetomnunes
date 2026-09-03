"""Read selectors for the finance domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.selectors import Selector as Selector

from .models import Charge, ChargeStatus, ServicePrice

__all__ = [
    "ChargeRow",
    "Selector",
    "charges_visible_to",
    "service_prices_for_clinic",
]


@dataclass(frozen=True, slots=True)
class ChargeRow:
    charge_id: UUID
    service_name: str
    amount: Decimal
    net_amount: Decimal
    currency: str
    due_date: date
    status: str
    appointment_start: str


def _finance_actor(*, clinic_id: UUID, actor: AbstractBaseUser) -> bool:
    today = timezone.localdate()
    return any(
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        )
        for role in ("clinic_admin", "administrative_staff")
    )


def service_prices_for_clinic(*, clinic_id: UUID) -> list[ServicePrice]:
    """Return active service prices for one clinic, newest first."""
    return list(
        ServicePrice.objects.for_clinic(clinic_id)
        .filter(is_active=True)
        .select_related("service")
        .order_by("-valid_from", "-created_at")
    )


def charges_visible_to(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    status: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[ChargeRow, ...]:
    """Return minimized charge rows for an authorized finance actor."""
    if not _finance_actor(clinic_id=clinic_id, actor=actor):
        return ()
    queryset = Charge.objects.for_clinic(clinic_id).select_related(
        "service", "appointment"
    )
    if status and status in ChargeStatus.values:
        queryset = queryset.filter(status=status)
    if period_start is not None:
        queryset = queryset.filter(due_date__gte=period_start)
    if period_end is not None:
        queryset = queryset.filter(due_date__lte=period_end)
    rows: list[ChargeRow] = []
    for charge in queryset.order_by("-due_date", "-created_at"):
        rows.append(
            ChargeRow(
                charge_id=charge.pk,
                service_name=charge.service.name,
                amount=charge.amount,
                net_amount=charge.net_amount,
                currency=charge.currency,
                due_date=charge.due_date,
                status=charge.status,
                appointment_start=(
                    charge.appointment.start_at.strftime("%d/%m/%Y %H:%M")
                    if charge.appointment_id
                    else ""
                ),
            )
        )
    return tuple(rows)
