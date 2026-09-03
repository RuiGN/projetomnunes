"""Authorization policies for tenant-scoped audit access."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as AuthorizationPolicy

__all__ = ["AuditRequester", "AuthorizationPolicy", "can_query_audit"]


class AuditRequester(Protocol):
    """Minimum authenticated actor contract required by audit services."""

    id: UUID


def can_query_audit(
    *, clinic_id: UUID, requester: AuditRequester, on_date: date
) -> bool:
    """Allow only an active clinic administrator with a current membership."""
    return has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=requester.id,
        role="clinic_admin",
        on_date=on_date,
    )
