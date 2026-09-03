"""Server-owned adapters for data lifecycle propagation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, cast
from uuid import UUID

from django.conf import settings
from django.core.cache import caches

from clinics.selectors import subject_has_clinic_relationship

from .models import LifecycleResult, ProcessingDestination


class LifecycleAdapter(Protocol):
    """Trusted adapter contract resolved exclusively by the server registry."""

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
        request_type: str,
        operation_id: UUID,
    ) -> LifecycleResult:
        """Apply one idempotent destination operation."""
        ...


@dataclass(frozen=True)
class DatabaseLifecycleAdapter:
    """Confirm the database boundary after revalidating its tenant relationship.

    For erasure requests, this adapter also performs the subject-scoped deletion
    of learning data (favorites and private notes) before confirming, so the
    primary-database destination reflects a real, audited erasure rather than a
    relationship check alone.
    """

    destination_key: str = "primary_database"
    adapter_identity: str = "privacy.database"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> LifecycleResult:
        if not subject_has_clinic_relationship(
            clinic_id=clinic_id,
            subject_id=subject_id,
        ):
            return LifecycleResult(
                destination_key=self.destination_key,
                outcome=ProcessingDestination.Status.FAILED,
                confirmation_reference="database:subject-relationship-missing",
            )
        if request_type == "erasure":
            from content.services import delete_learning_data_for_subject

            delete_learning_data_for_subject(clinic_id=clinic_id, subject_id=subject_id)
        return LifecycleResult(
            destination_key=self.destination_key,
            outcome=ProcessingDestination.Status.CONFIRMED,
            confirmation_reference=f"database:{operation_id}",
        )


@dataclass(frozen=True)
class CacheLifecycleAdapter:
    """Invalidate all configured subject cache aliases with an idempotent receipt."""

    destination_key: str = "default_cache"
    adapter_identity: str = "privacy.cache"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> LifecycleResult:
        aliases = tuple(getattr(settings, "PRIVACY_CACHE_ALIASES", ("default",)))
        keys = (
            f"privacy:subject:{clinic_id}:{subject_id}",
            f"privacy:lifecycle:{clinic_id}:{subject_id}:{request_type}",
        )
        for alias in aliases:
            caches[alias].delete_many(keys)
        return LifecycleResult(
            destination_key=self.destination_key,
            outcome=ProcessingDestination.Status.CONFIRMED,
            confirmation_reference=f"cache:{operation_id}",
        )


OperatorExecutor = Callable[..., LifecycleResult]


@dataclass(frozen=True)
class IntegratedOperatorLifecycleAdapter:
    """Invoke an operator executor selected only from trusted server settings."""

    destination_key: str = "external_processor"
    adapter_identity: str = "privacy.integrated_operator"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> LifecycleResult:
        configured = cast(
            Mapping[str, OperatorExecutor],
            getattr(settings, "PRIVACY_INTEGRATED_OPERATOR_HANDLERS", {}),
        )
        executor = configured.get(self.destination_key)
        if executor is None:
            return LifecycleResult(
                destination_key=self.destination_key,
                outcome=ProcessingDestination.Status.FAILED,
                confirmation_reference="operator:not-configured",
            )
        return executor(
            clinic_id=clinic_id,
            subject_id=subject_id,
            request_type=request_type,
            operation_id=operation_id,
        )


_LIFECYCLE_ADAPTERS: tuple[LifecycleAdapter, ...] = (
    DatabaseLifecycleAdapter(),
    CacheLifecycleAdapter(),
    IntegratedOperatorLifecycleAdapter(),
)

LIFECYCLE_ADAPTER_REGISTRY: Mapping[str, LifecycleAdapter] = MappingProxyType(
    {adapter.destination_key: adapter for adapter in _LIFECYCLE_ADAPTERS}
)


__all__ = [
    "LIFECYCLE_ADAPTER_REGISTRY",
    "CacheLifecycleAdapter",
    "DatabaseLifecycleAdapter",
    "IntegratedOperatorLifecycleAdapter",
    "LifecycleAdapter",
]
