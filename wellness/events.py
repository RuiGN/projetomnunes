"""Domain events and signals for the wellness domain."""

from __future__ import annotations

from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for wellness operations."""


activity_logged = Signal()
activity_device_synced = Signal()
overlapping_activities_resolved = Signal()

wellness_checkin_recorded = Signal()
movement_plan_proposed = Signal()
movement_plan_approved = Signal()
movement_plan_feedback_received = Signal()

sobriety_goal_created = Signal()
craving_recorded = Signal()
sobriety_milestone_achieved = Signal()
support_contact_registered = Signal()

relapse_plan_updated = Signal()
relapse_plan_shared = Signal()
relapse_plan_revoked = Signal()
post_lapse_recorded = Signal()

crisis_mode_accessed = Signal()
crisis_emergency_action_triggered = Signal()

__all__ = [
    "DomainEvent",
    "activity_device_synced",
    "activity_logged",
    "craving_recorded",
    "crisis_emergency_action_triggered",
    "crisis_mode_accessed",
    "movement_plan_approved",
    "movement_plan_feedback_received",
    "movement_plan_proposed",
    "overlapping_activities_resolved",
    "post_lapse_recorded",
    "relapse_plan_revoked",
    "relapse_plan_shared",
    "relapse_plan_updated",
    "sobriety_goal_created",
    "sobriety_milestone_achieved",
    "support_contact_registered",
    "wellness_checkin_recorded",
]
