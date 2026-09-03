"""Payment provider adapter contract and a deterministic fake for tests.

The adapter never receives or returns card data (PAN/CVV). It exchanges an
opaque provider token for a subscription and reports lifecycle events through
a normalized, idempotent interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    """Normalized result of a tokenized checkout."""

    provider_token: str
    status: str


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    """Normalized, sanitized provider event."""

    event_id: str
    event_type: str
    provider_token: str
    status: str
    raw_signature: str


class PaymentProvider(Protocol):
    """Contract implemented by every payment provider adapter."""

    def create_checkout(
        self, *, plan_code: str, amount: str, currency: str
    ) -> CheckoutResult:
        """Create a tokenized checkout and return an opaque provider token."""
        ...

    def process_webhook(self, *, payload: WebhookPayload) -> str:
        """Validate and normalize one provider event, returning its status."""
        ...


class FakePaymentProvider:
    """Deterministic in-memory provider used by tests and local development."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        self._events: list[WebhookPayload] = []

    def create_checkout(
        self, *, plan_code: str, amount: str, currency: str
    ) -> CheckoutResult:
        token = f"tok_{plan_code}_{len(self._tokens) + 1}"
        self._tokens[token] = "active"
        return CheckoutResult(provider_token=token, status="active")

    def process_webhook(self, *, payload: WebhookPayload) -> str:
        self._events.append(payload)
        if payload.provider_token not in self._tokens:
            return "unknown_token"
        self._tokens[payload.provider_token] = payload.status
        return payload.status


class FlakyPaymentProvider(FakePaymentProvider):
    """Provider that fails a bounded number of times before succeeding.

    Used to exercise retry/resume behavior without a real network dependency.
    """

    def __init__(self, failures: int = 1) -> None:
        super().__init__()
        self._remaining_failures = failures

    def create_checkout(
        self, *, plan_code: str, amount: str, currency: str
    ) -> CheckoutResult:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise TimeoutError("provider timeout")
        return super().create_checkout(
            plan_code=plan_code, amount=amount, currency=currency
        )
