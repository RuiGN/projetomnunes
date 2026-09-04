"""Transactional services for WhatsApp messaging and consent (8.13.2)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .contracts import (
    FakeWhatsAppAdapter,
    MessagingAdapter,
)
from .events import message_dispatched
from .whatsapp_models import (
    WhatsAppConsentRecord,
    WhatsAppConsentStatus,
    WhatsAppDeliveryStatus,
    WhatsAppInboundMessage,
    WhatsAppMessageTimeline,
    WhatsAppParsedAction,
    WhatsAppTemplate,
    validate_no_clinical_content,
)

# ---------------------------------------------------------------------------
# Consent Services (8.13.2.1)
# ---------------------------------------------------------------------------


@transaction.atomic
def record_whatsapp_consent(
    *,
    clinic_id: UUID,
    phone_number: str,
    purpose: str = "appointment_reminders",
    patient_user_id: UUID | None = None,
    consent_text: str = "",
    consent_version: str = "1.0",
    actor_id: UUID | None = None,
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> WhatsAppConsentRecord:
    """Record explicit opt-in consent for WhatsApp communication."""
    normalized_phone = re.sub(r"[^\d+]", "", phone_number)
    if not normalized_phone:
        raise ValidationError("Número de telefone inválido.")

    record, _ = WhatsAppConsentRecord.objects.update_or_create(
        clinic_id=clinic_id,
        phone_number=normalized_phone,
        purpose=purpose,
        defaults={
            "patient_user_id": patient_user_id,
            "status": WhatsAppConsentStatus.ACTIVE,
            "consent_version": consent_version,
            "consent_text_snapshot": consent_text,
            "granted_at": timezone.now(),
            "revoked_at": None,
            "revocation_reason": "",
        },
    )

    if actor_id:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor_id,
            action="integration.whatsapp_consent_granted",
            resource_type="whatsapp_consent",
            resource_id=str(record.id),
            outcome="success",
            request_id=request_id or uuid4(),
            network_origin=network_origin,
        )

    return record


@transaction.atomic
def revoke_whatsapp_consent(
    *,
    clinic_id: UUID,
    phone_number: str,
    purpose: str = "appointment_reminders",
    reason: str = "opt_out",
    actor_id: UUID | None = None,
    request_id: UUID | None = None,
    network_origin: str | None = None,
) -> WhatsAppConsentRecord:
    """Revoke WhatsApp consent immediately and record audit evidence."""
    normalized_phone = re.sub(r"[^\d+]", "", phone_number)
    record = WhatsAppConsentRecord.objects.filter(
        clinic_id=clinic_id,
        phone_number=normalized_phone,
        purpose=purpose,
    ).first()

    now = timezone.now()
    if not record:
        record = WhatsAppConsentRecord.objects.create(
            clinic_id=clinic_id,
            phone_number=normalized_phone,
            purpose=purpose,
            status=WhatsAppConsentStatus.REVOKED,
            revoked_at=now,
            revocation_reason=reason,
        )
    else:
        record.status = WhatsAppConsentStatus.REVOKED
        record.revoked_at = now
        record.revocation_reason = reason
        record.save(
            update_fields=[
                "status",
                "revoked_at",
                "revocation_reason",
                "updated_at",
            ]
        )

    if actor_id:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor_id,
            action="integration.whatsapp_consent_revoked",
            resource_type="whatsapp_consent",
            resource_id=str(record.id),
            outcome="success",
            request_id=request_id or uuid4(),
            network_origin=network_origin,
        )

    return record


def has_valid_whatsapp_consent(
    *,
    clinic_id: UUID,
    phone_number: str,
    purpose: str = "appointment_reminders",
) -> bool:
    """Check whether active, unrevoked consent exists for this phone and purpose."""
    normalized_phone = re.sub(r"[^\d+]", "", phone_number)
    return WhatsAppConsentRecord.objects.filter(
        clinic_id=clinic_id,
        phone_number=normalized_phone,
        purpose=purpose,
        status=WhatsAppConsentStatus.ACTIVE,
    ).exists()


# ---------------------------------------------------------------------------
# Template Catalog Services (8.13.2.2)
# ---------------------------------------------------------------------------


def create_whatsapp_template(
    *,
    clinic_id: UUID,
    name: str,
    body_template: str,
    language: str = "pt_BR",
    category: str = "UTILITY",
) -> WhatsAppTemplate:
    """Create an approved administrative template validated against clinical leakage."""
    validate_no_clinical_content(body_template)
    template, _ = WhatsAppTemplate.objects.update_or_create(
        clinic_id=clinic_id,
        name=name,
        language=language,
        defaults={
            "category": category,
            "body_template": body_template,
            "is_approved": True,
        },
    )
    return template


def render_whatsapp_template(
    *,
    template: WhatsAppTemplate,
    parameters: Mapping[str, str],
) -> str:
    """Render template parameters.

    Ensures resulting text remains clinically neutral.
    """
    try:
        rendered = template.body_template.format(**parameters)
    except KeyError as exc:
        raise ValidationError(f"Parâmetro obrigatório ausente: {exc}") from exc

    validate_no_clinical_content(rendered)
    return rendered


# ---------------------------------------------------------------------------
# Outbound Dispatch and Timeline Services (8.13.2.4)
# ---------------------------------------------------------------------------


@transaction.atomic
def send_whatsapp_message(
    *,
    clinic_id: UUID,
    recipient_phone: str,
    template_name: str,
    parameters: Mapping[str, str],
    purpose: str = "appointment_reminders",
    appointment_id: UUID | None = None,
    adapter: MessagingAdapter | None = None,
    fallback_channel: str = "",
) -> WhatsAppMessageTimeline:
    """Send an administrative WhatsApp template message if consent is active."""
    normalized_phone = re.sub(r"[^\d+]", "", recipient_phone)

    # 1. Gate: Verify consent
    if not has_valid_whatsapp_consent(
        clinic_id=clinic_id, phone_number=normalized_phone, purpose=purpose
    ):
        raise PermissionDenied(
            f"Consentimento para WhatsApp ausente para o número {normalized_phone}."
        )

    # 2. Gate: Find and validate template
    template = WhatsAppTemplate.objects.filter(
        clinic_id=clinic_id, name=template_name, is_approved=True
    ).first()
    if not template:
        raise ValidationError(
            f"Template aprovado '{template_name}' não encontrado para a clínica."
        )

    # Validate parameters render safely
    render_whatsapp_template(template=template, parameters=parameters)

    actual_adapter = adapter or FakeWhatsAppAdapter()
    idempotency_key = f"wa_{clinic_id}_{appointment_id or uuid4()}_{template_name}"

    now = timezone.now()
    timeline = WhatsAppMessageTimeline.objects.create(
        clinic_id=clinic_id,
        appointment_id=appointment_id,
        recipient_phone=normalized_phone,
        template_name=template_name,
        status=WhatsAppDeliveryStatus.PENDING,
        fallback_channel=fallback_channel,
    )

    try:
        result = actual_adapter.send_template_message(
            recipient_phone=normalized_phone,
            template_name=template_name,
            template_params=parameters,
            idempotency_key=idempotency_key,
        )
        timeline.provider_message_id = result.provider_message_id
        timeline.status = WhatsAppDeliveryStatus.SENT
        timeline.sent_at = now
        timeline.save(
            update_fields=[
                "provider_message_id",
                "status",
                "sent_at",
                "updated_at",
            ]
        )
        message_dispatched.send(sender=WhatsAppMessageTimeline, timeline=timeline)
    except Exception as exc:
        timeline.status = WhatsAppDeliveryStatus.FAILED
        timeline.failed_at = now
        timeline.error_details = str(exc)
        timeline.save(
            update_fields=["status", "failed_at", "error_details", "updated_at"]
        )

    return timeline


@transaction.atomic
def update_whatsapp_delivery_status(
    *,
    provider_message_id: str,
    status: str,
    error_details: str = "",
) -> WhatsAppMessageTimeline | None:
    """Update status on message delivery receipt or read notification."""
    timeline = WhatsAppMessageTimeline.objects.filter(
        provider_message_id=provider_message_id
    ).first()
    if not timeline:
        return None

    now = timezone.now()
    if status.lower() == "delivered":
        timeline.status = WhatsAppDeliveryStatus.DELIVERED
        timeline.delivered_at = now
        timeline.save(update_fields=["status", "delivered_at", "updated_at"])
    elif status.lower() == "read":
        timeline.status = WhatsAppDeliveryStatus.READ
        timeline.read_at = now
        timeline.save(update_fields=["status", "read_at", "updated_at"])
    elif status.lower() == "failed":
        timeline.status = WhatsAppDeliveryStatus.FAILED
        timeline.failed_at = now
        timeline.error_details = error_details
        timeline.save(
            update_fields=["status", "failed_at", "error_details", "updated_at"]
        )

    return timeline


# ---------------------------------------------------------------------------
# Inbound Replies and Action Parsing (8.13.2.3)
# ---------------------------------------------------------------------------


def parse_inbound_action(text: str) -> WhatsAppParsedAction:
    """Parse patient response deterministically into an actionable intent."""
    cleaned = re.sub(r"[^\w\s]", " ", text.strip().lower())
    words = set(cleaned.split())

    # Priority 1: Opt-out
    if {"parar", "stop", "sair", "optout", "bloquear"}.intersection(words):
        return WhatsAppParsedAction.OPT_OUT

    # Priority 2: Confirmation
    if {"1", "sim", "confirmar", "confirmo", "confirma"}.intersection(words):
        return WhatsAppParsedAction.CONFIRM

    # Priority 3: Reschedule
    if {"2", "remarcar", "remarca"}.intersection(words):
        return WhatsAppParsedAction.RESCHEDULE

    # Priority 4: Cancellation
    if {"0", "cancelar", "cancelo", "cancela", "nao", "não"}.intersection(words):
        return WhatsAppParsedAction.CANCEL

    return WhatsAppParsedAction.UNKNOWN


@transaction.atomic
def process_inbound_whatsapp_reply(
    *,
    clinic_id: UUID,
    sender_phone: str,
    external_message_id: str,
    raw_text: str,
    correlation_token: str = "",
    appointment_id: UUID | None = None,
) -> WhatsAppInboundMessage:
    """Process incoming WhatsApp message, deduce action and trigger lifecycle."""
    normalized_phone = re.sub(r"[^\d+]", "", sender_phone)

    # Deduplicate inbound message
    existing = WhatsAppInboundMessage.objects.filter(
        external_message_id=external_message_id
    ).first()
    if existing:
        return existing

    action = parse_inbound_action(raw_text)

    inbound = WhatsAppInboundMessage.objects.create(
        clinic_id=clinic_id,
        sender_phone=normalized_phone,
        external_message_id=external_message_id,
        correlation_token=correlation_token,
        raw_text=raw_text[:500],
        action_parsed=action,
        appointment_id=appointment_id,
        processed=False,
    )

    # Handle actions
    if action == WhatsAppParsedAction.OPT_OUT:
        revoke_whatsapp_consent(
            clinic_id=clinic_id,
            phone_number=normalized_phone,
            reason="Solicitado pelo paciente via mensagem 'PARAR'",
        )
        inbound.processed = True
        inbound.save(update_fields=["processed", "updated_at"])

    elif action == WhatsAppParsedAction.CONFIRM and appointment_id:
        try:
            from scheduling.selectors import appointment_for_integrations
            from scheduling.services import confirm_appointment

            appt = appointment_for_integrations(
                clinic_id=clinic_id, appointment_id=appointment_id
            )
            if appt and appt.professional:
                confirm_appointment(
                    clinic_id=clinic_id,
                    appointment_id=appointment_id,
                    actor=appt.professional,
                    request_id=uuid4(),
                )
        except Exception:
            pass  # Fail-safe; record inbound regardless
        inbound.processed = True
        inbound.save(update_fields=["processed", "updated_at"])

    elif action == WhatsAppParsedAction.CANCEL and appointment_id:
        try:
            from scheduling.selectors import appointment_for_integrations
            from scheduling.services import cancel_appointment

            appt = appointment_for_integrations(
                clinic_id=clinic_id, appointment_id=appointment_id
            )
            if appt and appt.professional:
                cancel_appointment(
                    clinic_id=clinic_id,
                    appointment_id=appointment_id,
                    actor=appt.professional,
                    reason="Cancelado pelo paciente via WhatsApp",
                    request_id=uuid4(),
                )
        except Exception:
            pass
        inbound.processed = True
        inbound.save(update_fields=["processed", "updated_at"])

    return inbound


__all__ = [
    "create_whatsapp_template",
    "has_valid_whatsapp_consent",
    "parse_inbound_action",
    "process_inbound_whatsapp_reply",
    "record_whatsapp_consent",
    "render_whatsapp_template",
    "revoke_whatsapp_consent",
    "send_whatsapp_message",
    "update_whatsapp_delivery_status",
]
