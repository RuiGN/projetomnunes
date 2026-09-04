"""Domain events and signals for external integrations."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for integration operations."""


credential_stored = Signal()
credential_rotated = Signal()
credential_revoked = Signal()
webhook_received = Signal()
webhook_processed = Signal()
webhook_dead_lettered = Signal()
message_dispatched = Signal()
calendar_synchronized = Signal()
video_room_provisioned = Signal()
video_session_created = Signal()
video_session_closed = Signal()
appointment_saga_completed = Signal()
appointment_saga_compensated = Signal()

# Sprint 20 API, Webhooks, CSV, Wearables, Offline & Rollout Signals
api_client_registered = Signal()
api_client_secret_rotated = Signal()
api_client_revoked = Signal()
api_token_issued = Signal()
api_token_revoked = Signal()
webhook_dispatched = Signal()
webhook_replayed = Signal()
csv_import_completed = Signal()
csv_export_generated = Signal()
wearable_connected = Signal()
wearable_revoked = Signal()
offline_sync_item_queued = Signal()
offline_sync_conflict_detected = Signal()
offline_sync_resolved = Signal()
partner_agreement_updated = Signal()
rollout_flag_updated = Signal()
rollout_emergency_rollback = Signal()

__all__ = [
    "DomainEvent",
    "api_client_registered",
    "api_client_revoked",
    "api_client_secret_rotated",
    "api_token_issued",
    "api_token_revoked",
    "appointment_saga_compensated",
    "appointment_saga_completed",
    "calendar_synchronized",
    "credential_revoked",
    "credential_rotated",
    "credential_stored",
    "csv_export_generated",
    "csv_import_completed",
    "message_dispatched",
    "offline_sync_conflict_detected",
    "offline_sync_item_queued",
    "offline_sync_resolved",
    "partner_agreement_updated",
    "rollout_emergency_rollback",
    "rollout_flag_updated",
    "video_room_provisioned",
    "video_session_closed",
    "video_session_created",
    "wearable_connected",
    "wearable_revoked",
    "webhook_dead_lettered",
    "webhook_dispatched",
    "webhook_processed",
    "webhook_received",
    "webhook_replayed",
]
