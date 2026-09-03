"""Domain event contracts owned by finance."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

charge_generated = Signal()
charge_settled = Signal()
charge_canceled = Signal()

__all__ = [
    "DomainEvent",
    "charge_canceled",
    "charge_generated",
    "charge_settled",
]
