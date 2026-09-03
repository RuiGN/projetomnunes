"""Domain event contracts owned by goals."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

goal_created = Signal()
goal_updated = Signal()
goal_completed = Signal()
goal_reopened = Signal()
goal_due_date_changed = Signal()
goal_visibility_changed = Signal()
goal_step_done = Signal()
goal_step_undone = Signal()

__all__ = [
    "DomainEvent",
    "goal_completed",
    "goal_created",
    "goal_due_date_changed",
    "goal_reopened",
    "goal_step_done",
    "goal_step_undone",
    "goal_updated",
    "goal_visibility_changed",
]
