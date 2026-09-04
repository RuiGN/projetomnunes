"""Service layer for crisis mode access and emergency one-touch actions (8.15.5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .events import crisis_emergency_action_triggered, crisis_mode_accessed
from .models import (
    CrisisAccessLog,
)


class CrisisService(CoreService[Any, Any]):
    """Crisis domain service base."""


@transaction.atomic
def log_crisis_mode_access(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    action_invoked: str = "viewed_disclaimer",
    offline_mode_active: bool = False,
    actor_id: UUID | None = None,
) -> CrisisAccessLog:
    """Log crisis mode entry ensuring mandatory disclaimer is visible."""
    now = timezone.now()
    log = CrisisAccessLog.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        accessed_at=now,
        action_invoked=action_invoked,
        confirmation_requested=False,
        confirmation_granted=True,
        offline_mode_active=offline_mode_active,
    )

    crisis_mode_accessed.send(sender=CrisisAccessLog, log=log)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.crisis_mode_accessed",
        resource_type="crisis_access_log",
        resource_id=str(log.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return log


@transaction.atomic
def trigger_emergency_touch_action(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    action_invoked: str,  # e.g., "call_samu_192", "call_cvv_188"
    confirmation_confirmed: bool,
    actor_id: UUID | None = None,
) -> CrisisAccessLog:
    """Execute one-touch action requiring user confirmation before dialing."""
    if not confirmation_confirmed:
        raise ValidationError(
            "Confirmação explícita do usuário é obrigatória antes de acionar chamada."
        )

    now = timezone.now()
    log = CrisisAccessLog.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        accessed_at=now,
        action_invoked=action_invoked,
        confirmation_requested=True,
        confirmation_granted=True,
        offline_mode_active=False,
    )

    crisis_emergency_action_triggered.send(sender=CrisisAccessLog, log=log)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.emergency_action_confirmed",
        resource_type="crisis_access_log",
        resource_id=str(log.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return log


__all__ = [
    "CrisisService",
    "log_crisis_mode_access",
    "trigger_emergency_touch_action",
]
