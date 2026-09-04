"""Domain events and signals for communities, moderation, and gamification (8.17)."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for community operations."""


# Community group signals
community_group_created = Signal()
community_group_closed = Signal()

# Membership signals
membership_joined = Signal()
membership_left = Signal()
membership_status_changed = Signal()

# Interaction signals
post_published = Signal()
post_edited = Signal()
post_deleted = Signal()
comment_published = Signal()
reaction_added = Signal()

# Safety & Moderation signals
user_blocked = Signal()
user_muted = Signal()
moderation_case_opened = Signal()
moderation_actioned = Signal()
moderation_appeal_filed = Signal()
moderation_appeal_resolved = Signal()

# Gamification signals
gamification_opted_in = Signal()
gamification_paused = Signal()
gamification_progress_logged = Signal()
gamification_history_purged = Signal()

# Governance signals
rollout_flag_updated = Signal()
moderation_kill_switch_triggered = Signal()

__all__ = [
    "DomainEvent",
    "comment_published",
    "community_group_closed",
    "community_group_created",
    "gamification_history_purged",
    "gamification_opted_in",
    "gamification_paused",
    "gamification_progress_logged",
    "membership_joined",
    "membership_left",
    "membership_status_changed",
    "moderation_actioned",
    "moderation_appeal_filed",
    "moderation_appeal_resolved",
    "moderation_case_opened",
    "moderation_kill_switch_triggered",
    "post_deleted",
    "post_edited",
    "post_published",
    "reaction_added",
    "rollout_flag_updated",
    "user_blocked",
    "user_muted",
]

