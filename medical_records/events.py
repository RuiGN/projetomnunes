"""Domain events and signals for medical records, documents and signatures (8.18)."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for medical records operations."""


# Clinical episode & entry signals
episode_created = Signal()
record_entry_created = Signal()
record_entry_updated = Signal()
record_entry_signed = Signal()
addendum_created = Signal()
addendum_signed = Signal()

# Document pipeline signals
document_uploaded_to_quarantine = Signal()
document_scan_completed = Signal()
document_promoted = Signal()
document_rejected = Signal()
document_access_logged = Signal()

# Signature signals
signature_applied = Signal()
signature_revoked = Signal()
signature_challenge_issued = Signal()

# Retention & legal hold signals
legal_hold_instituted = Signal()
legal_hold_released = Signal()
disposal_batch_created = Signal()
disposal_batch_approved = Signal()
disposal_batch_executed = Signal()
disposal_certificate_issued = Signal()

# Governance & export signals
medical_records_read_only_activated = Signal()
medical_records_read_only_deactivated = Signal()
medical_record_export_requested = Signal()
medical_record_export_ready = Signal()
