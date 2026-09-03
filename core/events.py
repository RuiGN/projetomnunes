"""Infrastructure-neutral domain event contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Immutable metadata shared by every domain event."""

    event_id: UUID
    occurred_at: datetime
    actor_id: UUID
    tenant_id: UUID


class EventPublisher(Protocol):
    """Publish a domain event without coupling to transport infrastructure."""

    def publish(self, event: DomainEvent, /) -> None:
        """Publish one event."""
        ...
