"""Abstract adapter contracts and deterministic test fakes for external integrations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


class IntegrationError(Exception):
    """Base exception for all integration operations."""


class ProviderUnavailableError(IntegrationError):
    """Provider endpoint or network is unreachable or returning 5xx."""


class CredentialExpiredError(IntegrationError):
    """Integration credentials have expired and must be refreshed or rotated."""


class InvalidSignatureError(IntegrationError):
    """Inbound webhook signature could not be verified."""


class AdapterConfigurationError(IntegrationError):
    """Adapter misconfigured or missing mandatory capability/credential."""


class RateLimitExceededError(IntegrationError):
    """Provider API rate limit reached."""


class ApiAuthenticationError(IntegrationError):
    """Client could not be authenticated via credentials or bearer token."""


class ApiAuthorizationError(IntegrationError):
    """Client is not authorized for the requested resource."""


class ScopeInsufficientError(ApiAuthorizationError):
    """Token lacks required scope for this operation."""


class IdempotencyConflictError(IntegrationError):
    """Idempotency key reused with mismatched request payload."""


class WearableClinicalUseForbiddenError(IntegrationError):
    """Wearable metrics cannot be used for clinical decision, triage or diagnosis."""


class CsvSecurityViolationError(IntegrationError):
    """CSV payload contains unsafe formulas or invalid quarantined data."""


class OfflineSyncConflictError(IntegrationError):
    """Offline mutation conflicts with current server state."""


class PartnerComplianceError(IntegrationError):
    """Partner fails mandatory data protection, SLA, or residency compliance."""


@dataclass(frozen=True, slots=True)
class MessageDeliveryResult:
    """Normalized result of an outbound message dispatch."""

    provider_message_id: str
    status: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookResult:
    """Normalized result of an inbound webhook parsing."""

    event_id: str
    event_type: str
    provider: str
    payload: dict[str, Any]
    timestamp: datetime | None
    is_valid: bool


@dataclass(frozen=True, slots=True)
class CalendarSyncEvent:
    """Normalized calendar appointment event for external synchronization."""

    external_id: str
    title: str
    start_time: datetime
    end_time: datetime
    description: str
    status: str
    version: int = 1


@dataclass(frozen=True, slots=True)
class VideoRoomResult:
    """Normalized result of video room provisioning."""

    room_id: str
    join_url: str
    expires_at: datetime
    status: str = "open"


class MessagingAdapter(Protocol):
    """Contract for external messaging providers (e.g. WhatsApp)."""

    def send_template_message(
        self,
        *,
        recipient_phone: str,
        template_name: str,
        template_params: Mapping[str, str],
        idempotency_key: str,
    ) -> MessageDeliveryResult:
        """Send a pre-approved transactional template message."""
        ...

    def validate_webhook_signature(
        self,
        *,
        raw_payload: bytes,
        signature_header: str,
        timestamp_header: str | None = None,
    ) -> bool:
        """Validate signature and freshness of an inbound webhook."""
        ...

    def parse_webhook_event(
        self,
        *,
        raw_payload: bytes,
    ) -> WebhookResult:
        """Parse and normalize raw provider webhook data."""
        ...


class CalendarAdapter(Protocol):
    """Contract for external calendar providers (Google Calendar, Outlook)."""

    def sync_event(
        self,
        *,
        event: CalendarSyncEvent,
        idempotency_key: str,
    ) -> str:
        """Create or update an event in the external calendar.

        Returns its external ID.
        """
        ...

    def cancel_event(
        self,
        *,
        external_event_id: str,
        idempotency_key: str,
    ) -> bool:
        """Cancel/delete an event in the external calendar."""
        ...

    def fetch_changes(
        self,
        *,
        sync_cursor: str | None,
    ) -> tuple[list[CalendarSyncEvent], str]:
        """Fetch incremental updates since cursor, returning events and new cursor."""
        ...


class VideoAdapter(Protocol):
    """Contract for external video conference providers."""

    def create_room(
        self,
        *,
        appointment_id: UUID,
        scheduled_start: datetime,
        duration_minutes: int,
        host_user_id: UUID,
        participant_user_id: UUID,
    ) -> VideoRoomResult:
        """Create a dedicated, isolated video room for an appointment."""
        ...

    def generate_participant_token(
        self,
        *,
        room_id: str,
        user_id: UUID,
        role: str,
        expires_at: datetime,
    ) -> str:
        """Generate a short-lived token for a participant to access the room."""
        ...

    def close_room(
        self,
        *,
        room_id: str,
    ) -> bool:
        """Close and invalidate an existing video room."""
        ...


# ---------------------------------------------------------------------------
# Deterministic Test Fakes
# ---------------------------------------------------------------------------


class FakeWhatsAppAdapter:
    """Deterministic in-memory WhatsApp adapter for tests."""

    def __init__(self, secret: str = "fake-secret-key-1234") -> None:
        self.secret = secret
        self.sent_messages: list[dict[str, Any]] = []
        self._counter = 0

    def send_template_message(
        self,
        *,
        recipient_phone: str,
        template_name: str,
        template_params: Mapping[str, str],
        idempotency_key: str,
    ) -> MessageDeliveryResult:
        for msg in self.sent_messages:
            if msg["idempotency_key"] == idempotency_key:
                return MessageDeliveryResult(
                    provider_message_id=msg["provider_message_id"],
                    status="sent",
                )

        self._counter += 1
        msg_id = f"wamid.fake.{self._counter}"
        self.sent_messages.append(
            {
                "idempotency_key": idempotency_key,
                "provider_message_id": msg_id,
                "recipient_phone": recipient_phone,
                "template_name": template_name,
                "template_params": dict(template_params),
                "timestamp": datetime.now(UTC),
            }
        )
        return MessageDeliveryResult(provider_message_id=msg_id, status="sent")

    def validate_webhook_signature(
        self,
        *,
        raw_payload: bytes,
        signature_header: str,
        timestamp_header: str | None = None,
    ) -> bool:
        import hashlib
        import hmac

        if not signature_header.startswith("sha256="):
            return False
        expected = (
            "sha256="
            + hmac.new(
                self.secret.encode("utf-8"), raw_payload, hashlib.sha256
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature_header)

    def parse_webhook_event(
        self,
        *,
        raw_payload: bytes,
    ) -> WebhookResult:
        import json

        data = json.loads(raw_payload.decode("utf-8"))
        event_id = data.get("id", f"evt_{len(self.sent_messages)}")
        event_type = data.get("type", "message_status")
        return WebhookResult(
            event_id=event_id,
            event_type=event_type,
            provider="whatsapp",
            payload=data,
            timestamp=datetime.now(UTC),
            is_valid=True,
        )


class FakeCalendarAdapter:
    """Deterministic in-memory Calendar adapter for tests."""

    def __init__(self) -> None:
        self.events: dict[str, CalendarSyncEvent] = {}
        self.canceled_events: set[str] = set()
        self._counter = 0

    def sync_event(
        self,
        *,
        event: CalendarSyncEvent,
        idempotency_key: str,
    ) -> str:
        ext_id = event.external_id or f"cal_evt_{self._counter + 1}"
        self._counter += 1
        stored = CalendarSyncEvent(
            external_id=ext_id,
            title=event.title,
            start_time=event.start_time,
            end_time=event.end_time,
            description=event.description,
            status=event.status,
            version=event.version,
        )
        self.events[ext_id] = stored
        return ext_id

    def cancel_event(
        self,
        *,
        external_event_id: str,
        idempotency_key: str,
    ) -> bool:
        if external_event_id in self.events:
            self.canceled_events.add(external_event_id)
            del self.events[external_event_id]
            return True
        return False

    def fetch_changes(
        self,
        *,
        sync_cursor: str | None,
    ) -> tuple[list[CalendarSyncEvent], str]:
        new_cursor = f"cursor_{len(self.events)}"
        return list(self.events.values()), new_cursor


class FakeVideoAdapter:
    """Deterministic in-memory Video provider adapter for tests."""

    def __init__(self) -> None:
        self.rooms: dict[str, VideoRoomResult] = {}
        self._counter = 0

    def create_room(
        self,
        *,
        appointment_id: UUID,
        scheduled_start: datetime,
        duration_minutes: int,
        host_user_id: UUID,
        participant_user_id: UUID,
    ) -> VideoRoomResult:
        self._counter += 1
        room_id = f"room_{appointment_id}_{self._counter}"
        expires_at = scheduled_start
        result = VideoRoomResult(
            room_id=room_id,
            join_url=f"https://video.fake.internal/rooms/{room_id}",
            expires_at=expires_at,
            status="open",
        )
        self.rooms[room_id] = result
        return result

    def generate_participant_token(
        self,
        *,
        room_id: str,
        user_id: UUID,
        role: str,
        expires_at: datetime,
    ) -> str:
        return f"vtoken_{room_id}_{user_id}_{role}_{int(expires_at.timestamp())}"

    def close_room(
        self,
        *,
        room_id: str,
    ) -> bool:
        if room_id in self.rooms:
            self.rooms[room_id] = VideoRoomResult(
                room_id=room_id,
                join_url=self.rooms[room_id].join_url,
                expires_at=self.rooms[room_id].expires_at,
                status="closed",
            )
            return True
        return False


# ---------------------------------------------------------------------------
# Sprint 20 Scopes, Catalogues and Error Constants
# ---------------------------------------------------------------------------

ALLOWED_API_SCOPES: frozenset[str] = frozenset(
    {
        "patients:read",
        "patients:write",
        "appointments:read",
        "appointments:write",
        "activities:read",
        "activities:write",
        "documents:read",
        "documents:write",
    }
)

FORBIDDEN_API_SCOPES: frozenset[str] = frozenset(
    {
        "medical_records:read",
        "medical_records:write",
        "clinical_ai:diagnose",
        "clinical_ai:prescribe",
        "clinical_decision:automated",
    }
)

WEBHOOK_ALLOWED_EVENTS: frozenset[str] = frozenset(
    {
        "patient.registered",
        "patient.updated",
        "appointment.scheduled",
        "appointment.rescheduled",
        "appointment.cancelled",
        "activity.assigned",
        "activity.completed",
    }
)

WEBHOOK_FORBIDDEN_EVENTS: frozenset[str] = frozenset(
    {
        "medical_record.viewed",
        "medical_record.entry_created",
        "clinical_note.created",
        "ai_assistant.draft_generated",
        "clinical_decision.automated",
    }
)


class ApiErrorCode:
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    SCOPE_INSUFFICIENT = "SCOPE_INSUFFICIENT"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    REVOKED_CLIENT = "REVOKED_CLIENT"
    WEARABLE_CLINICAL_USE_FORBIDDEN = "WEARABLE_CLINICAL_USE_FORBIDDEN"
    OFFLINE_SYNC_CONFLICT = "OFFLINE_SYNC_CONFLICT"
    PARTNER_NON_COMPLIANT = "PARTNER_NON_COMPLIANT"
