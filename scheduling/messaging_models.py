"""Conversations, participants, immutable messages and private attachments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel

from .storage import PrivateAttachmentStorage


class ConversationKind(models.TextChoices):
    CLINICAL = "clinical", "Clínica"
    ADMINISTRATIVE = "administrative", "Administrativa"


class ScanStatus(models.TextChoices):
    QUARANTINED = "quarantined", "Em quarentena"
    CLEAN = "clean", "Aprovado"
    FAILED = "failed", "Reprovado"


def message_attachment_upload_to(instance: MessageAttachment, filename: str) -> str:
    """Build an opaque tenant-owned private path without the supplied filename."""
    suffix = Path(filename).suffix.lower()
    clinic_id = cast(Any, instance).clinic_id
    return f"scheduling/{clinic_id}/attachments/{uuid4().hex}{suffix}"


class ConversationQuerySet(models.QuerySet["Conversation"]):
    def for_clinic(self, clinic_id: UUID) -> ConversationQuerySet:
        return self.filter(clinic_id=clinic_id)


class ConversationManager(models.Manager["Conversation"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Conversation queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ConversationQuerySet:
        return ConversationQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureConversationManager(models.Manager["Conversation"]):
    def get_queryset(self) -> ConversationQuerySet:
        return ConversationQuerySet(self.model, using=self._db)


class Conversation(UUIDTimestampedModel):
    """One typed asynchronous thread between bound participants."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    kind = models.CharField(max_length=32, choices=ConversationKind.choices)
    subject = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conversations_created",
    )
    is_active = models.BooleanField(default=True)

    objects = ConversationManager()
    infrastructure_objects = InfrastructureConversationManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(fields=("clinic", "kind", "is_active"), name="conv_kind_idx"),
        ]

    def __str__(self) -> str:
        return self.subject or f"{self.get_kind_display()} ({self.pk})"


class ConversationParticipantQuerySet(models.QuerySet["ConversationParticipant"]):
    def for_clinic(self, clinic_id: UUID) -> ConversationParticipantQuerySet:
        return self.filter(clinic_id=clinic_id)


class ConversationParticipantManager(models.Manager["ConversationParticipant"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "ConversationParticipant queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ConversationParticipantQuerySet:
        return ConversationParticipantQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureConversationParticipantManager(
    models.Manager["ConversationParticipant"]
):
    def get_queryset(self) -> ConversationParticipantQuerySet:
        return ConversationParticipantQuerySet(self.model, using=self._db)


class ConversationParticipant(UUIDTimestampedModel):
    """One user's membership in a conversation."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="conversation_participants",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
    )
    is_active = models.BooleanField(default=True)

    objects = ConversationParticipantManager()
    infrastructure_objects = InfrastructureConversationParticipantManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "user"),
                name="unique_participant_per_conversation",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "user", "is_active"),
                name="participant_user_idx",
            ),
        ]


class MessageQuerySet(models.QuerySet["Message"]):
    def for_clinic(self, clinic_id: UUID) -> MessageQuerySet:
        return self.filter(clinic_id=clinic_id)


class MessageManager(models.Manager["Message"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Message queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> MessageQuerySet:
        return MessageQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureMessageManager(models.Manager["Message"]):
    def get_queryset(self) -> MessageQuerySet:
        return MessageQuerySet(self.model, using=self._db)


class Message(UUIDTimestampedModel):
    """One immutable message inside a conversation."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="messages_sent",
    )
    body = models.TextField()

    objects = MessageManager()
    infrastructure_objects = InfrastructureMessageManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("clinic", "conversation", "created_at"),
                name="message_conv_created_idx",
            ),
        ]


class MessageReadReceiptQuerySet(models.QuerySet["MessageReadReceipt"]):
    def for_clinic(self, clinic_id: UUID) -> MessageReadReceiptQuerySet:
        return self.filter(clinic_id=clinic_id)


class MessageReadReceiptManager(models.Manager["MessageReadReceipt"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("MessageReadReceipt queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> MessageReadReceiptQuerySet:
        return MessageReadReceiptQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureMessageReadReceiptManager(models.Manager["MessageReadReceipt"]):
    def get_queryset(self) -> MessageReadReceiptQuerySet:
        return MessageReadReceiptQuerySet(self.model, using=self._db)


class MessageReadReceipt(UUIDTimestampedModel):
    """One participant's read confirmation for one message."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="message_read_receipts",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="read_receipts",
    )
    participant = models.ForeignKey(
        ConversationParticipant,
        on_delete=models.CASCADE,
        related_name="read_receipts",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    objects = MessageReadReceiptManager()
    infrastructure_objects = InfrastructureMessageReadReceiptManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("message", "participant"),
                name="unique_read_receipt_per_participant",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "message"),
                name="receipt_message_idx",
            ),
        ]


class MessageAttachmentQuerySet(models.QuerySet["MessageAttachment"]):
    def for_clinic(self, clinic_id: UUID) -> MessageAttachmentQuerySet:
        return self.filter(clinic_id=clinic_id)


class MessageAttachmentManager(models.Manager["MessageAttachment"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("MessageAttachment queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> MessageAttachmentQuerySet:
        return MessageAttachmentQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureMessageAttachmentManager(models.Manager["MessageAttachment"]):
    def get_queryset(self) -> MessageAttachmentQuerySet:
        return MessageAttachmentQuerySet(self.model, using=self._db)


class MessageAttachment(UUIDTimestampedModel):
    """One private, quarantined attachment belonging to a message."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="message_attachments",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="message_attachments",
    )
    file = models.FileField(
        upload_to=message_attachment_upload_to,
        storage=PrivateAttachmentStorage(),
        max_length=255,
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.PositiveBigIntegerField()
    scan_status = models.CharField(
        max_length=16, choices=ScanStatus.choices, default=ScanStatus.QUARANTINED
    )

    objects = MessageAttachmentManager()
    infrastructure_objects = InfrastructureMessageAttachmentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "message"),
                name="attachment_message_idx",
            ),
        ]
