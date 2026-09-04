"""Domain events and signals for support network (8.16)."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for support network operations."""


invitation_created = Signal()
invitation_accepted = Signal()
invitation_declined = Signal()
invitation_revoked = Signal()

relationship_revoked = Signal()
permission_updated = Signal()

guardian_consent_registered = Signal()
guardian_consent_verified = Signal()
guardian_consent_revoked = Signal()
guardian_consent_disputed = Signal()

minor_guardrail_evaluated = Signal()
minor_transitioned_to_adult = Signal()

urgent_plan_updated = Signal()
urgent_action_previewed = Signal()
urgent_action_confirmed = Signal()

spirituality_preference_updated = Signal()
contemplative_history_purged = Signal()

__all__ = [
    "DomainEvent",
    "contemplative_history_purged",
    "guardian_consent_disputed",
    "guardian_consent_registered",
    "guardian_consent_revoked",
    "guardian_consent_verified",
    "invitation_accepted",
    "invitation_created",
    "invitation_declined",
    "invitation_revoked",
    "minor_guardrail_evaluated",
    "minor_transitioned_to_adult",
    "permission_updated",
    "relationship_revoked",
    "spirituality_preference_updated",
    "urgent_action_confirmed",
    "urgent_action_previewed",
    "urgent_plan_updated",
]
