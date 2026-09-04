from dataclasses import dataclass

from django.dispatch import Signal

from core.events import DomainEvent as CoreDomainEvent


@dataclass(frozen=True, slots=True)
class DomainEvent(CoreDomainEvent):
    """Base domain event for routine operations."""


habit_created = Signal()
habit_paused = Signal()
habit_resumed = Signal()
habit_checked_in = Signal()

medication_registered = Signal()
medication_dose_logged = Signal()

sleep_entry_created = Signal()
sleep_device_synced = Signal()

care_plan_proposed = Signal()
care_plan_signed = Signal()
care_plan_response_received = Signal()

__all__ = [
    "DomainEvent",
    "care_plan_proposed",
    "care_plan_response_received",
    "care_plan_signed",
    "habit_checked_in",
    "habit_created",
    "habit_paused",
    "habit_resumed",
    "medication_dose_logged",
    "medication_registered",
    "sleep_device_synced",
    "sleep_entry_created",
]
