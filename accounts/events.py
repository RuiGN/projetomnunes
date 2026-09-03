"""Domain event contracts owned by accounts."""

from dataclasses import dataclass
from uuid import UUID

from django.dispatch import Signal

from core.events import DomainEvent

# Emitted for side effects the audit domain must persist. The payload carries
# only minimized technical metadata; no clinical or credential content.
account_audit_required = Signal()

# Emitted after a consumed patient invitation links its accepted identity.
invitation_accepted = Signal()


@dataclass(frozen=True, slots=True)
class InvitationCreated(DomainEvent):
    """An account invitation was created inside a tenant."""

    invitation_id: UUID


__all__ = [
    "DomainEvent",
    "InvitationCreated",
    "account_audit_required",
    "invitation_accepted",
]
