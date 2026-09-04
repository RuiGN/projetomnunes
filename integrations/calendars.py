"""External calendar synchronization services and OAuth state (8.13.3)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from scheduling.selectors import (
    AppointmentStatus,
    appointment_for_integrations,
)

from .contracts import (
    CalendarAdapter,
    CalendarSyncEvent,
    FakeCalendarAdapter,
)
from .events import calendar_synchronized
from .models import (
    CredentialStatus,
    ExternalCalendarMapping,
    IntegrationCredential,
)

# ---------------------------------------------------------------------------
# OAuth Connection & Anti-CSRF Helpers (8.13.3.1)
# ---------------------------------------------------------------------------


def generate_oauth_state(
    *,
    clinic_id: UUID,
    user_id: UUID,
    provider: str,
) -> str:
    """Generate a signed, tamper-proof anti-CSRF state token with expiry."""
    secret = settings.SECRET_KEY
    payload = {
        "clinic_id": str(clinic_id),
        "user_id": str(user_id),
        "provider": provider,
        "nonce": secrets.token_hex(16),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = hashlib.sha256(secret.encode("utf-8") + raw).digest()
    token_bytes = raw + b"." + sig
    return base64.urlsafe_b64encode(token_bytes).decode("ascii")


def validate_oauth_state(state_token: str) -> dict[str, Any]:
    """Validate and decode the anti-CSRF state token."""
    try:
        token_bytes = base64.urlsafe_b64decode(state_token.encode("ascii"))
        if b"." not in token_bytes:
            raise ValidationError("Formato do estado OAuth inválido.")
        raw, sig = token_bytes.rsplit(b".", 1)
        expected_sig = hashlib.sha256(
            settings.SECRET_KEY.encode("utf-8") + raw
        ).digest()
        if not secrets.compare_digest(sig, expected_sig):
            raise ValidationError("Assinatura do estado OAuth inválida.")
        data = cast(dict[str, Any], json.loads(raw.decode("utf-8")))
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(UTC) > expires_at:
            raise ValidationError("Estado OAuth expirado.")
        return data
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Falha na validação do estado OAuth: {exc}") from exc


def check_calendar_authorization_status(
    *,
    clinic_id: UUID,
    provider: str = "google_calendar",
) -> dict[str, Any]:
    """Inspect whether external calendar authorization is active or expiring soon."""
    cred = (
        IntegrationCredential.objects.for_clinic(clinic_id)
        .filter(provider=provider, status=CredentialStatus.ACTIVE)
        .first()
    )
    if not cred:
        return {
            "authorized": False,
            "status": "missing",
            "warning": "Nenhuma credencial configurada.",
        }

    expires_at_str = cred.metadata.get("token_expires_at")
    warning = ""
    is_expiring_soon = False

    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            now = datetime.now(UTC)
            if now >= expires_at:
                return {
                    "authorized": False,
                    "status": "expired",
                    "warning": "Autorização do calendário expirada.",
                }
            elif (expires_at - now).total_seconds() < 86400 * 3:
                is_expiring_soon = True
                warning = (
                    "Autorização do calendário expira em menos de 3 dias. "
                    "Reautorize a conexão."
                )
        except ValueError:
            pass

    return {
        "authorized": True,
        "status": "active",
        "expiring_soon": is_expiring_soon,
        "warning": warning,
        "calendar_id": cred.metadata.get("calendar_id", "primary"),
    }


# ---------------------------------------------------------------------------
# Bidirectional Synchronization Engine (8.13.3.2 / 8.13.3.3)
# ---------------------------------------------------------------------------


@transaction.atomic
def sync_appointment_to_external_calendar(
    *,
    clinic_id: UUID,
    appointment_id: UUID,
    provider: str = "google_calendar",
    adapter: CalendarAdapter | None = None,
    custom_title: str | None = None,
) -> ExternalCalendarMapping:
    """Synchronize an appointment to an external calendar with minimized details."""
    appt = appointment_for_integrations(
        clinic_id=clinic_id, appointment_id=appointment_id
    )
    if not appt:
        raise ValidationError(f"Agendamento {appointment_id} não encontrado.")

    mapping = (
        ExternalCalendarMapping.objects.for_clinic(clinic_id)
        .filter(appointment_id=appointment_id, provider=provider)
        .first()
    )

    actual_adapter = adapter or FakeCalendarAdapter()
    idempotency_key = f"sync_{clinic_id}_{appointment_id}_{provider}"

    # Neutral non-clinical title and description per PRD
    safe_title = custom_title or "Atendimento Clínico Reservado"
    safe_description = (
        "Horário reservado pela plataforma terapêutica. "
        "Não altere diretamente para evitar conflitos de sincronização."
    )

    is_canceled = appt.status == AppointmentStatus.CANCELED

    if mapping:
        current_version = mapping.version + 1
        sync_event = CalendarSyncEvent(
            external_id=mapping.external_event_id,
            title=safe_title,
            start_time=appt.start_at,
            end_time=appt.end_at,
            description=safe_description,
            status="canceled" if is_canceled else "confirmed",
            version=current_version,
        )

        if is_canceled:
            actual_adapter.cancel_event(
                external_event_id=mapping.external_event_id,
                idempotency_key=f"{idempotency_key}_cancel_{current_version}",
            )
            mapping.sync_status = "canceled"
        else:
            actual_adapter.sync_event(
                event=sync_event,
                idempotency_key=f"{idempotency_key}_update_{current_version}",
            )
            mapping.sync_status = "synced"

        mapping.version = current_version
        mapping.save(
            update_fields=[
                "version",
                "sync_status",
                "last_synced_at",
                "updated_at",
            ]
        )
    else:
        sync_event = CalendarSyncEvent(
            external_id="",
            title=safe_title,
            start_time=appt.start_at,
            end_time=appt.end_at,
            description=safe_description,
            status="confirmed",
            version=1,
        )
        ext_id = actual_adapter.sync_event(
            event=sync_event,
            idempotency_key=f"{idempotency_key}_create_1",
        )
        mapping = ExternalCalendarMapping.objects.for_clinic(clinic_id).create(
            clinic_id=clinic_id,
            appointment_id=appointment_id,
            provider=provider,
            external_calendar_id="primary",
            external_event_id=ext_id,
            version=1,
            sync_status="synced",
        )

    calendar_synchronized.send(sender=ExternalCalendarMapping, mapping=mapping)
    return mapping


# ---------------------------------------------------------------------------
# Conflict Resolution Center (8.13.3.4)
# ---------------------------------------------------------------------------


class ConflictResolutionStrategy:
    PREFER_INTERNAL = "prefer_internal"
    PREFER_EXTERNAL = "prefer_external"
    MANUAL_REVIEW = "manual_review"


@transaction.atomic
def record_calendar_conflict(
    *,
    clinic_id: UUID,
    mapping_id: UUID,
    conflict_type: str,
    remote_data: dict[str, Any],
    actor_id: UUID | None = None,
) -> ExternalCalendarMapping:
    """Record a detected sync conflict in the mapping record."""
    mapping = (
        ExternalCalendarMapping.objects.for_clinic(clinic_id)
        .filter(pk=mapping_id)
        .select_for_update()
        .first()
    )
    if not mapping:
        raise ValidationError("Mapeamento de calendário não encontrado.")

    mapping.sync_status = "conflict"
    mapping.conflict_details = {
        "conflict_type": conflict_type,
        "remote_data": remote_data,
        "detected_at": timezone.now().isoformat(),
    }
    mapping.save(update_fields=["sync_status", "conflict_details", "updated_at"])

    if actor_id:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor_id,
            action="integration.calendar_conflict_detected",
            resource_type="calendar_mapping",
            resource_id=str(mapping.id),
            outcome="warning",
            request_id=uuid4(),
            network_origin=None,
        )

    return mapping


@transaction.atomic
def resolve_calendar_conflict(
    *,
    clinic_id: UUID,
    mapping_id: UUID,
    strategy: str,
    actor_id: UUID,
    adapter: CalendarAdapter | None = None,
) -> ExternalCalendarMapping:
    """Resolve conflict deterministically or manually with audit trail."""
    mapping = (
        ExternalCalendarMapping.objects.for_clinic(clinic_id)
        .filter(pk=mapping_id)
        .select_for_update()
        .first()
    )
    if not mapping:
        raise ValidationError("Mapeamento de calendário não encontrado.")

    if strategy == ConflictResolutionStrategy.PREFER_INTERNAL:
        # Re-push internal appointment over external
        sync_appointment_to_external_calendar(
            clinic_id=clinic_id,
            appointment_id=mapping.appointment_id,
            provider=mapping.provider,
            adapter=adapter,
        )
        mapping.sync_status = "synced"
        mapping.conflict_details = {
            "resolved_strategy": strategy,
            "resolved_at": timezone.now().isoformat(),
        }
        mapping.save(update_fields=["sync_status", "conflict_details", "updated_at"])

    elif strategy == ConflictResolutionStrategy.PREFER_EXTERNAL:
        # External overrides: mark resolved and update status
        mapping.sync_status = "synced"
        mapping.conflict_details = {
            "resolved_strategy": strategy,
            "resolved_at": timezone.now().isoformat(),
        }
        mapping.save(update_fields=["sync_status", "conflict_details", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="integration.calendar_conflict_resolved",
        resource_type="calendar_mapping",
        resource_id=str(mapping.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )

    return mapping


__all__ = [
    "ConflictResolutionStrategy",
    "check_calendar_authorization_status",
    "generate_oauth_state",
    "record_calendar_conflict",
    "resolve_calendar_conflict",
    "sync_appointment_to_external_calendar",
    "validate_oauth_state",
]
