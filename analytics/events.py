"""Domain event contracts owned by analytics."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

report_generated = Signal()
report_downloaded = Signal()

__all__ = [
    "DomainEvent",
    "report_downloaded",
    "report_generated",
]
