"""Domain event contracts owned by scheduling."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

appointment_requested = Signal()
appointment_confirmed = Signal()
appointment_reschedule_requested = Signal()
appointment_canceled = Signal()
appointment_completed = Signal()
appointment_no_show = Signal()
reminder_scheduled = Signal()
reminder_canceled = Signal()
conversation_created = Signal()
message_sent = Signal()
attachment_uploaded = Signal()

__all__ = [
    "DomainEvent",
    "appointment_canceled",
    "appointment_completed",
    "appointment_confirmed",
    "appointment_no_show",
    "appointment_requested",
    "appointment_reschedule_requested",
    "attachment_uploaded",
    "conversation_created",
    "message_sent",
    "reminder_canceled",
    "reminder_scheduled",
]
