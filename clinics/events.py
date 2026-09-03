"""Domain event contracts owned by clinics."""

from dataclasses import dataclass
from uuid import UUID

from django.dispatch import Signal

from core.events import DomainEvent

clinic_configuration_updated = Signal()
professional_membership_updated = Signal()
whitelabel_audit_required = Signal()


@dataclass(frozen=True, slots=True)
class ClinicCreated(DomainEvent):
    """A clinic was created inside a tenant."""

    clinic_id: UUID


__all__ = [
    "ClinicCreated",
    "DomainEvent",
    "clinic_configuration_updated",
    "professional_membership_updated",
    "whitelabel_audit_required",
]
