"""Consent operational notifications exposed to authorized tenant templates."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest
from django.utils import timezone

from clinics.policies import has_active_clinic_role

from .models import ConsentRevocationWorkItem


def revocation_work_notifications(request: HttpRequest) -> dict[str, Any]:
    """Return a minimized pending count only for an active clinic administrator."""
    actor = request.user
    clinic_id = getattr(getattr(request, "clinic", None), "pk", None)
    if not isinstance(actor, AbstractBaseUser) or not isinstance(clinic_id, UUID):
        return {"pending_consent_revocation_count": 0}
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        return {"pending_consent_revocation_count": 0}
    count = (
        ConsentRevocationWorkItem.objects.for_clinic(clinic_id)
        .filter(status=ConsentRevocationWorkItem.Status.OPEN)
        .count()
    )
    return {"pending_consent_revocation_count": count}
