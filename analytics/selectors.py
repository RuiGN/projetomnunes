"""Read selectors for the analytics domain."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.selectors import Selector as Selector

from .models import Report

__all__ = ["Selector", "reports_visible_to"]


def reports_visible_to(*, clinic_id: UUID, actor: AbstractBaseUser) -> list[Report]:
    """Return reports the actor may see: own individual, or all for clinic admin."""
    today = timezone.localdate()
    if has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="clinic_admin", on_date=today
    ):
        return list(Report.objects.for_clinic(clinic_id).order_by("-created_at"))
    return list(
        Report.objects.for_clinic(clinic_id)
        .filter(generated_by_id=actor.pk)
        .order_by("-created_at")
    )
