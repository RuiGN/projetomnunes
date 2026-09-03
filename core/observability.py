"""Request-local structured observability without sensitive payload capture."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="unknown")
_TENANT_ID: ContextVar[str] = ContextVar("tenant_id", default="unknown")
_ACTOR_REF: ContextVar[str] = ContextVar("actor_ref", default="anonymous")


def current_request_id() -> str:
    """Return the correlation identifier bound to the current execution context."""
    return _REQUEST_ID.get()


def _actor_reference(actor_id: str | None) -> str:
    if not actor_id:
        return "anonymous"
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:16]
    return f"actor_{digest}"


def bind_request_context(
    *, request_id: str, tenant_id: str | None = None, actor_id: str | None = None
) -> Callable[[], None]:
    """Bind safe request metadata and return an idempotent reset callback."""
    tokens: tuple[tuple[ContextVar[str], Token[str]], ...] = (
        (_REQUEST_ID, _REQUEST_ID.set(request_id)),
        (_TENANT_ID, _TENANT_ID.set(tenant_id or "unknown")),
        (_ACTOR_REF, _ACTOR_REF.set(_actor_reference(actor_id))),
    )
    reset = False

    def restore() -> None:
        nonlocal reset
        if reset:
            return
        for variable, token in reversed(tokens):
            variable.reset(token)
        reset = True

    return restore


def update_request_context(
    *, tenant_id: str | None = None, actor_id: str | None = None
) -> None:
    """Add authorized tenant/actor identifiers to the current request context."""
    if tenant_id is not None:
        _TENANT_ID.set(tenant_id)
    if actor_id is not None:
        _ACTOR_REF.set(_actor_reference(actor_id))


class JsonLogFormatter(logging.Formatter):
    """Serialize an allowlist of operational fields as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": _REQUEST_ID.get(),
            "tenant_id": _TENANT_ID.get(),
            "actor_ref": _ACTOR_REF.get(),
            "event": self._safe_text(getattr(record, "event", "log.event")),
            "outcome": self._safe_text(getattr(record, "outcome", "unknown")),
        }
        latency = getattr(record, "latency_ms", None)
        if isinstance(latency, int | float) and not isinstance(latency, bool):
            payload["latency_ms"] = round(float(latency), 3)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _safe_text(value: object) -> str:
        if isinstance(value, str):
            return value[:128]
        return "unknown"
