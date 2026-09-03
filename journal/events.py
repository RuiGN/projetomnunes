"""Domain event contracts owned by journal."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

journal_entry_created = Signal()
journal_entry_updated = Signal()
journal_entry_visibility_changed = Signal()
journal_entry_sharing_granted = Signal()
journal_entry_access_requested = Signal()
journal_entry_sharing_revoked = Signal()
daily_checkin_submitted = Signal()
daily_checkin_updated = Signal()
human_triage_item_created = Signal()
human_triage_item_reviewed = Signal()

__all__ = [
    "DomainEvent",
    "daily_checkin_submitted",
    "daily_checkin_updated",
    "human_triage_item_created",
    "human_triage_item_reviewed",
    "journal_entry_access_requested",
    "journal_entry_created",
    "journal_entry_sharing_granted",
    "journal_entry_sharing_revoked",
    "journal_entry_updated",
    "journal_entry_visibility_changed",
]
