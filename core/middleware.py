"""Cross-cutting HTTP middleware for safe request correlation."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from time import monotonic
from uuid import uuid4

from django.http import HttpRequest, HttpResponse

from .observability import bind_request_context

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_REQUEST_ID_HEADER = "X-Request-ID"
logger = logging.getLogger("application.request")


def _safe_request_id(candidate: str | None) -> str:
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


class RequestCorrelationMiddleware:
    """Own one bounded request ID for the full middleware/response lifecycle."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = _safe_request_id(request.headers.get(_REQUEST_ID_HEADER))
        request.request_id = request_id  # type: ignore[attr-defined]
        reset_context = bind_request_context(request_id=request_id)
        started_at = monotonic()
        outcome = "error"
        try:
            response = self.get_response(request)
            response.headers[_REQUEST_ID_HEADER] = request_id
            outcome = "success" if response.status_code < 500 else "error"
            return response
        finally:
            latency_ms = (monotonic() - started_at) * 1000
            logger.info(
                "request completed",
                extra={
                    "event": "request.completed",
                    "outcome": outcome,
                    "latency_ms": latency_ms,
                },
            )
            reset_context()
