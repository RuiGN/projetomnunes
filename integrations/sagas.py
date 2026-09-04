"""Appointment integration saga orchestrator and circuit breaker (8.13.5)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_audit_event
from scheduling.selectors import appointment_for_integrations

from .calendars import sync_appointment_to_external_calendar
from .contracts import (
    CalendarAdapter,
    FakeCalendarAdapter,
    MessagingAdapter,
    VideoAdapter,
)
from .events import appointment_saga_compensated, appointment_saga_completed
from .models import (
    AppointmentSaga,
    ExternalCalendarMapping,
    VideoSession,
    WebhookEvent,
    WebhookStatus,
)
from .video import close_video_session, create_clinical_video_session
from .whatsapp import has_valid_whatsapp_consent, send_whatsapp_message

# ---------------------------------------------------------------------------
# Circuit Breaker & Fallback Manager (8.13.5.3)
# ---------------------------------------------------------------------------


class CircuitBreakerState:
    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: int = 60,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, datetime] = {}
        self._simulated_failures: set[str] = set()

    def is_open(self, provider: str) -> bool:
        """Return True if circuit is open (requests should be tripped to fallback)."""
        if provider in self._simulated_failures:
            return True

        opened = self._opened_at.get(provider)
        if not opened:
            return False

        if (datetime.now(UTC) - opened).total_seconds() > self.reset_timeout_seconds:
            # Half-open / reset
            del self._opened_at[provider]
            self._failures[provider] = 0
            return False
        return True

    def record_success(self, provider: str) -> None:
        self._failures[provider] = 0
        self._opened_at.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        count = self._failures.get(provider, 0) + 1
        self._failures[provider] = count
        if count >= self.failure_threshold:
            self._opened_at[provider] = datetime.now(UTC)

    def set_simulation(self, provider: str, should_fail: bool) -> None:
        if should_fail:
            self._simulated_failures.add(provider)
        else:
            self._simulated_failures.discard(provider)


circuit_breaker = CircuitBreakerState()


# ---------------------------------------------------------------------------
# Transactional Saga Orchestration (8.13.5.1 / 8.13.5.2)
# ---------------------------------------------------------------------------


class SagaStatus:
    STARTED = "started"
    COMPLETED = "completed"
    COMPLETED_WITH_FALLBACK = "completed_with_fallback"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


@transaction.atomic
def execute_appointment_saga(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    calendar_provider: str = "google_calendar",
    send_whatsapp_notification: bool = True,
    whatsapp_recipient_phone: str = "",
    whatsapp_template_name: str = "",
    whatsapp_params: Mapping[str, str] | None = None,
    calendar_adapter: CalendarAdapter | None = None,
    video_adapter: VideoAdapter | None = None,
    messaging_adapter: MessagingAdapter | None = None,
    actor_id: UUID | None = None,
) -> AppointmentSaga:
    """Execute multi-integration appointment journey with transactional compensation."""
    appt = appointment_for_integrations(
        clinic_id=clinic_id, appointment_id=appointment_id
    )
    if not appt:
        raise ValidationError(f"Agendamento {appointment_id} não encontrado.")

    saga = AppointmentSaga.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        correlation_id=uuid4(),
        current_step="internal_reservation",
        status=SagaStatus.STARTED,
        steps_completed=["internal_reservation"],
        compensation_log=[],
    )

    completed_steps = list(saga.steps_completed)
    fallbacks_applied = []

    # Step 2: External Calendar Sync
    saga.current_step = "calendar_sync"
    saga.save(update_fields=["current_step", "updated_at"])

    if circuit_breaker.is_open(calendar_provider):
        fallbacks_applied.append(f"calendar:{calendar_provider}_tripped")
    else:
        try:
            sync_appointment_to_external_calendar(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
                provider=calendar_provider,
                adapter=calendar_adapter,
            )
            completed_steps.append("calendar_sync")
            circuit_breaker.record_success(calendar_provider)
        except Exception as exc:
            circuit_breaker.record_failure(calendar_provider)
            _compensate_saga(saga=saga, failed_step="calendar_sync", error=str(exc))
            return saga

    # Step 3: Clinical Video Session Provisioning
    saga.current_step = "video_provisioning"
    saga.steps_completed = completed_steps
    saga.save(update_fields=["current_step", "steps_completed", "updated_at"])

    video_provider = "daily_co"
    if circuit_breaker.is_open(video_provider):
        fallbacks_applied.append(f"video:{video_provider}_tripped")
    else:
        try:
            create_clinical_video_session(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
                adapter=video_adapter,
            )
            completed_steps.append("video_provisioning")
            circuit_breaker.record_success(video_provider)
        except Exception as exc:
            circuit_breaker.record_failure(video_provider)
            _compensate_saga(
                saga=saga,
                failed_step="video_provisioning",
                error=str(exc),
                calendar_adapter=calendar_adapter,
                calendar_provider=calendar_provider,
            )
            return saga

    # Step 4: WhatsApp Reminder Notification
    should_send_wa = (
        send_whatsapp_notification
        and whatsapp_recipient_phone
        and whatsapp_template_name
    )
    if should_send_wa:
        saga.current_step = "whatsapp_notification"
        saga.steps_completed = completed_steps
        saga.save(update_fields=["current_step", "steps_completed", "updated_at"])

        wa_provider = "whatsapp"
        if circuit_breaker.is_open(wa_provider):
            fallbacks_applied.append(f"whatsapp:{wa_provider}_tripped")
        else:
            try:
                if has_valid_whatsapp_consent(
                    clinic_id=clinic_id, phone_number=whatsapp_recipient_phone
                ):
                    send_whatsapp_message(
                        clinic_id=clinic_id,
                        recipient_phone=whatsapp_recipient_phone,
                        template_name=whatsapp_template_name,
                        parameters=whatsapp_params or {},
                        appointment_id=appointment_id,
                        adapter=messaging_adapter,
                    )
                    completed_steps.append("whatsapp_notification")
                    circuit_breaker.record_success(wa_provider)
            except Exception as exc:
                circuit_breaker.record_failure(wa_provider)
                fallbacks_applied.append(f"whatsapp_error:{exc}")

    # Success / Completed
    saga.steps_completed = completed_steps
    saga.status = (
        SagaStatus.COMPLETED_WITH_FALLBACK
        if fallbacks_applied
        else SagaStatus.COMPLETED
    )
    saga.current_step = "finished"
    if fallbacks_applied:
        fallbacks_str = ", ".join(fallbacks_applied)
        saga.last_error = f"Degradações tratadas via fallback: {fallbacks_str}"
    saga.save(
        update_fields=[
            "steps_completed",
            "status",
            "current_step",
            "last_error",
            "updated_at",
        ]
    )

    appointment_saga_completed.send(sender=AppointmentSaga, saga=saga)

    if actor_id:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor_id,
            action="integration.appointment_saga_completed",
            resource_type="appointment_saga",
            resource_id=str(saga.id),
            outcome="success",
            request_id=uuid4(),
            network_origin=None,
        )

    return saga


def _compensate_saga(
    *,
    saga: AppointmentSaga,
    failed_step: str,
    error: str,
    calendar_adapter: CalendarAdapter | None = None,
    calendar_provider: str = "google_calendar",
    video_adapter: VideoAdapter | None = None,
) -> None:
    """Execute reverse compensation actions for all previously completed steps."""
    saga.status = SagaStatus.COMPENSATING
    saga.last_error = f"Falha na etapa {failed_step}: {error}"
    compensation_log = []

    # Rollback Video if completed
    if "video_provisioning" in saga.steps_completed:
        try:
            session = (
                VideoSession.objects.for_clinic(saga.clinic_id)
                .filter(appointment_id=saga.appointment_id)
                .first()
            )
            if session:
                close_video_session(
                    session_id=session.id,
                    actor_id=saga.clinic_id,
                    adapter=video_adapter,
                )
                compensation_log.append("video_provisioning_reverted")
        except Exception as exc:
            compensation_log.append(f"video_rollback_failed:{exc}")

    # Rollback Calendar if completed
    if "calendar_sync" in saga.steps_completed:
        try:
            mapping = (
                ExternalCalendarMapping.objects.for_clinic(saga.clinic_id)
                .filter(appointment_id=saga.appointment_id, provider=calendar_provider)
                .first()
            )
            if mapping:
                actual_cal_adapter = calendar_adapter or FakeCalendarAdapter()
                actual_cal_adapter.cancel_event(
                    external_event_id=mapping.external_event_id,
                    idempotency_key=f"comp_{saga.id}_{mapping.version}",
                )
                mapping.sync_status = "canceled"
                mapping.save(update_fields=["sync_status", "updated_at"])
                compensation_log.append("calendar_sync_reverted")
        except Exception as exc:
            compensation_log.append(f"calendar_rollback_failed:{exc}")

    saga.status = SagaStatus.COMPENSATED
    saga.compensation_log = compensation_log
    saga.save(update_fields=["status", "compensation_log", "last_error", "updated_at"])

    appointment_saga_compensated.send(sender=AppointmentSaga, saga=saga)


# ---------------------------------------------------------------------------
# Operational Dashboard & Reconcile (8.13.5.4)
# ---------------------------------------------------------------------------


def get_integration_operations_dashboard(*, clinic_id: UUID) -> dict[str, Any]:
    """Provide unified operational overview of integrations, retries and sagas."""
    sagas_qs = AppointmentSaga.objects.for_clinic(clinic_id)
    dead_letters_count = WebhookEvent.infrastructure_objects.filter(
        clinic_id=clinic_id, status=WebhookStatus.DEAD_LETTER
    ).count()

    wa_open = circuit_breaker.is_open("whatsapp")
    cal_open = circuit_breaker.is_open("google_calendar")
    vid_open = circuit_breaker.is_open("daily_co")

    return {
        "providers": {
            "whatsapp": {
                "circuit_open": wa_open,
                "status": "degraded" if wa_open else "healthy",
            },
            "google_calendar": {
                "circuit_open": cal_open,
                "status": "degraded" if cal_open else "healthy",
            },
            "daily_co": {
                "circuit_open": vid_open,
                "status": "degraded" if vid_open else "healthy",
            },
        },
        "sagas": {
            "total": sagas_qs.count(),
            "completed": sagas_qs.filter(status=SagaStatus.COMPLETED).count(),
            "completed_with_fallback": sagas_qs.filter(
                status=SagaStatus.COMPLETED_WITH_FALLBACK
            ).count(),
            "compensated": sagas_qs.filter(status=SagaStatus.COMPENSATED).count(),
            "failed": sagas_qs.filter(status=SagaStatus.FAILED).count(),
        },
        "dead_letters": {
            "pending_reprocessing": dead_letters_count,
        },
    }


@transaction.atomic
def reconcile_appointment_integrations(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    actor_id: UUID,
    calendar_adapter: CalendarAdapter | None = None,
    video_adapter: VideoAdapter | None = None,
) -> dict[str, Any]:
    """Reconcile calendar sync and video room on demand for an appointment."""
    cal_mapping = sync_appointment_to_external_calendar(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        adapter=calendar_adapter,
    )
    video_session = create_clinical_video_session(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        adapter=video_adapter,
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="integration.appointment_reconciled",
        resource_type="appointment",
        resource_id=str(appointment_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )

    return {
        "calendar_event_id": cal_mapping.external_event_id,
        "calendar_status": cal_mapping.sync_status,
        "video_room_id": video_session.room_id,
        "video_status": video_session.status,
    }


__all__ = [
    "CircuitBreakerState",
    "SagaStatus",
    "circuit_breaker",
    "execute_appointment_saga",
    "get_integration_operations_dashboard",
    "reconcile_appointment_integrations",
]
