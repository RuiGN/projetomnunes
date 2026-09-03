"""Server-owned adapters for consent revocation propagation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, cast
from uuid import UUID

from django.conf import settings


@dataclass(frozen=True, slots=True)
class RevocationDispatchResult:
    """Minimized result returned by one trusted destination adapter."""

    destination_key: str
    succeeded: bool
    confirmation_reference: str


class RevocationAdapter(Protocol):
    """Trusted idempotent adapter resolved exclusively by server registry."""

    @property
    def destination_key(self) -> str: ...

    @property
    def adapter_identity(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        purpose: str,
        operation_id: UUID,
    ) -> RevocationDispatchResult: ...


@dataclass(frozen=True, slots=True)
class ClinicOperationsRevocationAdapter:
    """Create durable clinic work and confirm only after acknowledgement."""

    destination_key: str = "clinic_operations"
    adapter_identity: str = "consents.clinic_operations"
    adapter_version: str = "2"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        purpose: str,
        operation_id: UUID,
    ) -> RevocationDispatchResult:
        from .models import ConsentRevocationDispatch, ConsentRevocationWorkItem

        dispatch = ConsentRevocationDispatch.infrastructure_objects.filter(
            pk=operation_id,
            clinic_id=clinic_id,
            destination=self.destination_key,
            manifestation__subject_id=subject_id,
            manifestation__purpose=purpose,
        ).first()
        if dispatch is None:
            return RevocationDispatchResult(
                destination_key=self.destination_key,
                succeeded=False,
                confirmation_reference="operational-work-item:dispatch-mismatch",
            )
        work_item, _created = (
            ConsentRevocationWorkItem.infrastructure_objects.get_or_create(
                dispatch=dispatch,
            )
        )
        if work_item.status != ConsentRevocationWorkItem.Status.ACKNOWLEDGED:
            return RevocationDispatchResult(
                destination_key=self.destination_key,
                succeeded=False,
                confirmation_reference=f"operational-work-item:open:{work_item.pk}",
            )
        return RevocationDispatchResult(
            destination_key=self.destination_key,
            succeeded=True,
            confirmation_reference=(
                f"operational-work-item:acknowledged:{work_item.pk}:"
                f"{work_item.acknowledgement_digest}"
            ),
        )


RevocationExecutor = Callable[..., RevocationDispatchResult]


@dataclass(frozen=True, slots=True)
class IntegratedRevocationAdapter:
    """Invoke an external handler selected only from trusted server settings."""

    destination_key: str = "external_processor"
    adapter_identity: str = "consents.integrated_processor"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        purpose: str,
        operation_id: UUID,
    ) -> RevocationDispatchResult:
        handlers = cast(
            Mapping[str, RevocationExecutor],
            getattr(settings, "CONSENT_REVOCATION_HANDLERS", {}),
        )
        executor = handlers.get(self.destination_key)
        if executor is None:
            return RevocationDispatchResult(
                destination_key=self.destination_key,
                succeeded=False,
                confirmation_reference="external-processor:not-configured",
            )
        return executor(
            clinic_id=clinic_id,
            subject_id=subject_id,
            purpose=purpose,
            operation_id=operation_id,
        )


_ADAPTERS: tuple[RevocationAdapter, ...] = (
    ClinicOperationsRevocationAdapter(),
    IntegratedRevocationAdapter(),
)

REVOCATION_ADAPTER_REGISTRY: Mapping[str, RevocationAdapter] = MappingProxyType(
    {adapter.destination_key: adapter for adapter in _ADAPTERS}
)

__all__ = [
    "REVOCATION_ADAPTER_REGISTRY",
    "ClinicOperationsRevocationAdapter",
    "IntegratedRevocationAdapter",
    "RevocationAdapter",
    "RevocationDispatchResult",
]
