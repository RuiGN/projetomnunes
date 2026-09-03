"""Domain event contracts owned by consents."""

from dataclasses import dataclass
from uuid import UUID

from core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class ConsentGranted(DomainEvent):
    """Consent was granted for a professional-patient relationship."""

    consent_id: UUID
    professional_id: UUID
    patient_id: UUID


@dataclass(frozen=True, slots=True)
class ConsentRevoked(DomainEvent):
    """Consent was revoked for a professional-patient relationship."""

    consent_id: UUID
    professional_id: UUID
    patient_id: UUID


__all__ = ["ConsentGranted", "ConsentRevoked", "DomainEvent"]
