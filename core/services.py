"""Service contract for explicit state-changing use cases."""

from typing import Protocol, TypeVar

from .observability import current_request_id as _current_request_id
from .observability import update_request_context as _update_request_context
from .uploads import (
    PrivateDownloadGrant,
    PrivateUploadMetadata,
    PrivateUploadPolicy,
    require_clean_malware_scan,
)

CommandT = TypeVar("CommandT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class Service(Protocol[CommandT, ResultT]):
    """Execute one explicit state-changing use case."""

    def execute(self, command: CommandT, /) -> ResultT:
        """Execute the command and return its typed result."""
        ...


def current_correlation_id() -> str:
    """Expose the request correlation ID through the public core boundary."""
    return _current_request_id()


def update_observability_context(
    *, tenant_id: str | None = None, actor_id: str | None = None
) -> None:
    """Publish authorized request identifiers to the observability context."""
    _update_request_context(tenant_id=tenant_id, actor_id=actor_id)


__all__ = [
    "PrivateDownloadGrant",
    "PrivateUploadMetadata",
    "PrivateUploadPolicy",
    "Service",
    "current_correlation_id",
    "require_clean_malware_scan",
    "update_observability_context",
]
