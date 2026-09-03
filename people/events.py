"""Domain event contracts owned by people."""

from dataclasses import dataclass
from uuid import UUID

from django.dispatch import Signal

from core.events import DomainEvent

professional_profile_updated = Signal()
patient_profile_updated = Signal()
care_relationship_changed = Signal()
patient_record_accessed = Signal()
professional_credential_audit_required = Signal()
professional_credential_revoked = Signal()


@dataclass(frozen=True, slots=True)
class ProfessionalPatientRelationshipCreated(DomainEvent):
    """A professional-patient relationship was created."""

    relationship_id: UUID
    professional_id: UUID
    patient_id: UUID


__all__ = [
    "DomainEvent",
    "ProfessionalPatientRelationshipCreated",
    "care_relationship_changed",
    "patient_profile_updated",
    "patient_record_accessed",
    "professional_credential_audit_required",
    "professional_credential_revoked",
    "professional_profile_updated",
]
