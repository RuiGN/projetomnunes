"""Domain event contracts owned by content."""

from django.dispatch import Signal

from core.events import DomainEvent as DomainEvent

content_published = Signal()
content_archived = Signal()

__all__ = [
    "DomainEvent",
    "content_archived",
    "content_published",
]
