"""Transactional append, query and export services for audit events."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.crypto import salted_hmac

from clinics.services import clinic_exists, lock_clinic_for_update
from core.services import Service as Service

from .models import AuditAction, AuditCheckpoint, AuditEvent, AuditOutcome
from .policies import AuditRequester, can_query_audit

__all__ = [
    "Service",
    "export_audit_events",
    "query_audit_events",
    "record_audit_event",
]


@transaction.atomic
def record_audit_event(
    *,
    clinic_id: UUID,
    actor_id: UUID | None,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str,
    outcome: AuditOutcome | str,
    request_id: UUID,
    network_origin: str | None,
    justification: str | None = None,
) -> AuditEvent:
    """Append one minimized event while serializing the clinic hash chain."""
    lock_clinic_for_update(clinic_id=clinic_id)
    previous = (
        AuditEvent.infrastructure_objects.filter(clinic_id=clinic_id)
        .order_by("-sequence")
        .first()
    )
    occurred_at = timezone.now()
    retention_days = int(getattr(settings, "AUDIT_RETENTION_DAYS", 2190))
    origin_digest = ""
    if network_origin:
        origin_digest = salted_hmac(
            "audit.network-origin",
            network_origin,
            secret=settings.SECRET_KEY,
            algorithm="sha256",
        ).hexdigest()
    justification_digest = ""
    if justification and justification.strip():
        justification_digest = salted_hmac(
            "audit.justification",
            justification.strip(),
            secret=settings.SECRET_KEY,
            algorithm="sha256",
        ).hexdigest()
    event = AuditEvent(
        clinic_id=clinic_id,
        sequence=previous.sequence + 1 if previous else 1,
        occurred_at=occurred_at,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id,
        network_origin_digest=origin_digest,
        justification_digest=justification_digest,
        previous_hash=previous.event_hash if previous else "",
        retention_until=occurred_at + timedelta(days=retention_days),
        event_hash="",
    )
    event.event_hash = event.expected_hash()
    event.save(force_insert=True)
    checkpoint, _created = AuditCheckpoint.objects.update_or_create(
        clinic_id=clinic_id,
        defaults={
            "terminal_sequence": event.sequence,
            "terminal_hash": event.event_hash,
            "signature": "",
        },
    )
    checkpoint.signature = checkpoint.expected_signature()
    checkpoint.save(update_fields=("signature", "updated_at"))
    return event


def _record_audit_access(
    *,
    clinic_id: UUID,
    requester: AuditRequester,
    outcome: AuditOutcome,
    action: AuditAction,
) -> None:
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=requester.id,
        action=action,
        resource_type="audit_event",
        resource_id=str(clinic_id),
        outcome=outcome,
        request_id=uuid4(),
        network_origin=None,
    )


def query_audit_events(
    *,
    clinic_id: UUID,
    requester: AuditRequester,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    actor_id: UUID | None = None,
    action: AuditAction | str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome | str | None = None,
) -> QuerySet[AuditEvent]:
    """Return authorized filtered events and audit the access attempt itself."""
    if not clinic_exists(clinic_id=clinic_id):
        raise PermissionDenied("Audit access requires an active clinic administrator.")
    allowed = can_query_audit(
        clinic_id=clinic_id,
        requester=requester,
        on_date=timezone.localdate(),
    )
    _record_audit_access(
        clinic_id=clinic_id,
        requester=requester,
        outcome=AuditOutcome.SUCCESS if allowed else AuditOutcome.DENIED,
        action=AuditAction.AUDIT_QUERY,
    )
    if not allowed:
        raise PermissionDenied("Audit access requires an active clinic administrator.")

    queryset = AuditEvent.objects.for_clinic(clinic_id)
    if occurred_from is not None:
        queryset = queryset.filter(occurred_at__gte=occurred_from)
    if occurred_to is not None:
        queryset = queryset.filter(occurred_at__lte=occurred_to)
    if actor_id is not None:
        queryset = queryset.filter(actor_id=actor_id)
    if action is not None:
        queryset = queryset.filter(action=action)
    if resource_type is not None:
        queryset = queryset.filter(resource_type=resource_type)
    if resource_id is not None:
        queryset = queryset.filter(resource_id=resource_id)
    if outcome is not None:
        queryset = queryset.filter(outcome=outcome)
    return queryset.order_by("occurred_at", "sequence")


def export_audit_events(*, clinic_id: UUID, requester: AuditRequester) -> str:
    """Export minimized technical fields to CSV and audit the export."""
    events = list(query_audit_events(clinic_id=clinic_id, requester=requester))
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "occurred_at",
            "sequence",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
            "request_id",
            "network_origin_digest",
            "justification_digest",
            "event_hash",
        )
    )
    for event in events:
        writer.writerow(
            (
                event.occurred_at.isoformat(),
                event.sequence,
                event.actor_id or "",
                event.action,
                event.resource_type,
                event.resource_id,
                event.outcome,
                event.request_id,
                event.network_origin_digest,
                event.justification_digest,
                event.event_hash,
            )
        )
    _record_audit_access(
        clinic_id=clinic_id,
        requester=requester,
        outcome=AuditOutcome.SUCCESS,
        action=AuditAction.EXPORT,
    )
    return output.getvalue()
