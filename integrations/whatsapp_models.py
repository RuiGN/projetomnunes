"""Persistence models for WhatsApp communications, consent, and delivery."""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel

# Words prohibited in administrative templates to prevent clinical leak
PROHIBITED_CLINICAL_TERMS = frozenset(
    {
        "depressao",
        "depressão",
        "ansiedade",
        "transtorno",
        "psiquiatria",
        "psiquiatrico",
        "psiquiátrico",
        "psicopatologia",
        "diagnostico",
        "diagnóstico",
        "medicamento",
        "remedio",
        "remédio",
        "prescricao",
        "prescrição",
        "sintoma",
        "cid",
        "suicidio",
        "suicídio",
        "crise",
        "recaida",
        "recaída",
    }
)


def validate_no_clinical_content(text: str) -> None:
    """Validate that template text is strictly administrative.

    Rejects any clinical diagnoses, psychiatric terms, or medications.
    """
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    words = set(normalized.split())
    found = words.intersection(PROHIBITED_CLINICAL_TERMS)
    if found:
        termo_list = ", ".join(sorted(found))
        raise ValidationError(
            f"Templates de WhatsApp não podem conter termos clínicos: {termo_list}."
        )


class WhatsAppConsentStatus(models.TextChoices):
    ACTIVE = "active", "Ativo"
    REVOKED = "revoked", "Revogado"


class WhatsAppDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    SENT = "sent", "Enviado"
    DELIVERED = "delivered", "Entregue"
    READ = "read", "Lido"
    FAILED = "failed", "Falha"


class WhatsAppParsedAction(models.TextChoices):
    CONFIRM = "confirm", "Confirmar"
    RESCHEDULE = "reschedule", "Remarcar"
    CANCEL = "cancel", "Cancelar"
    OPT_OUT = "opt_out", "Opt-out / Parar"
    UNKNOWN = "unknown", "Não reconhecido"


class WhatsAppConsentRecord(UUIDTimestampedModel):
    """Granular consent record for WhatsApp messaging by phone and purpose."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="whatsapp_consents",
    )
    patient_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="whatsapp_consents",
    )
    phone_number = models.CharField(max_length=32)
    purpose = models.CharField(max_length=64, default="appointment_reminders")
    status = models.CharField(
        max_length=32,
        choices=WhatsAppConsentStatus.choices,
        default=WhatsAppConsentStatus.ACTIVE,
    )
    consent_version = models.CharField(max_length=32, default="1.0")
    consent_text_snapshot = models.TextField(blank=True)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "phone_number", "purpose"],
                name="unique_whatsapp_consent_clinic_phone_purpose",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "phone_number", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.phone_number} - {self.purpose} ({self.status})"


class WhatsAppTemplate(UUIDTimestampedModel):
    """Catalog of approved administrative WhatsApp templates."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="whatsapp_templates",
    )
    name = models.CharField(max_length=128)
    language = models.CharField(max_length=16, default="pt_BR")
    category = models.CharField(max_length=64, default="UTILITY")
    body_template = models.TextField()
    is_approved = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "name", "language"],
                name="unique_whatsapp_template_clinic_name_lang",
            )
        ]
        ordering = ["name"]

    def clean(self) -> None:
        super().clean()
        if self.body_template:
            validate_no_clinical_content(self.body_template)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.language})"


class WhatsAppMessageTimeline(UUIDTimestampedModel):
    """Administrative delivery timeline tracking outbound WhatsApp communications."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="whatsapp_timeline_messages",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_messages",
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    recipient_phone = models.CharField(max_length=32)
    template_name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32,
        choices=WhatsAppDeliveryStatus.choices,
        default=WhatsAppDeliveryStatus.PENDING,
    )
    fallback_channel = models.CharField(max_length=32, blank=True)
    error_details = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "status", "-created_at"]),
            models.Index(fields=["provider_message_id"]),
        ]
        ordering = ["-created_at"]

    @property
    def masked_phone(self) -> str:
        phone = self.recipient_phone
        if len(phone) > 6:
            return phone[:4] + "*****" + phone[-2:]
        return phone


class WhatsAppInboundMessage(UUIDTimestampedModel):
    """Inbound message or reply from patient on WhatsApp."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="whatsapp_inbound_messages",
    )
    sender_phone = models.CharField(max_length=32)
    external_message_id = models.CharField(max_length=255, unique=True)
    correlation_token = models.CharField(max_length=64, blank=True)
    raw_text = models.CharField(max_length=500)
    action_parsed = models.CharField(
        max_length=32,
        choices=WhatsAppParsedAction.choices,
        default=WhatsAppParsedAction.UNKNOWN,
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_replies",
    )
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
