"""Conversations, immutable messages and private attachments."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.selectors import (
    active_membership_roles_for_users,
    subject_has_active_clinic_relationship,
)
from core.services import PrivateUploadPolicy, require_clean_malware_scan
from core.services import Service as Service
from people.selectors import linked_patients_for_therapist, patient_profile_for_user

from .events import attachment_uploaded, conversation_created, message_sent
from .models import (
    Conversation,
    ConversationKind,
    ConversationParticipant,
    Message,
    MessageAttachment,
    MessageReadReceipt,
    NotificationEvent,
    NotificationStatus,
    ReminderChannel,
    ScanStatus,
)

__all__ = [
    "Service",
    "add_attachment",
    "create_conversation",
    "delete_attachment",
    "download_attachment",
    "mark_conversation_read",
    "send_message",
]


def _require_active_member(*, clinic_id: UUID, user_id: UUID) -> None:
    if not subject_has_active_clinic_relationship(
        clinic_id=clinic_id, subject_id=user_id
    ):
        raise PermissionDenied


def _validate_clinical_links(
    *, clinic_id: UUID, roles: dict[UUID, str], on_date: date
) -> None:
    """Require an active care link for every patient in a clinical conversation."""
    patient_ids = {uid for uid, role in roles.items() if role == "patient"}
    therapist_ids = {
        uid for uid, role in roles.items() if role in {"therapist", "clinic_admin"}
    }
    for patient_user_id in patient_ids:
        profile = patient_profile_for_user(clinic_id=clinic_id, user_id=patient_user_id)
        if profile is None:
            raise ValidationError("Paciente sem perfil cadastrado nesta clínica.")
        linked = False
        for therapist_id in therapist_ids:
            rows = linked_patients_for_therapist(
                clinic_id=clinic_id, therapist_id=therapist_id, on_date=on_date
            )
            if any(row.patient_profile_id == profile.pk for row in rows):
                linked = True
                break
        if not linked:
            raise ValidationError(
                "Conversas clínicas exigem vínculo ativo entre paciente e profissional."
            )


@transaction.atomic
def create_conversation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    kind: str,
    subject: str,
    participant_ids: list[UUID],
    request_id: UUID,
) -> Conversation:
    """Create one typed conversation restricted to active, bound members (8.8.4.1)."""
    if kind not in ConversationKind.values:
        raise ValidationError("Tipo de conversa inválido.")
    _require_active_member(clinic_id=clinic_id, user_id=actor.pk)

    unique_participants = list(dict.fromkeys(participant_ids))
    if actor.pk not in unique_participants:
        unique_participants.append(actor.pk)
    for user_id in unique_participants:
        _require_active_member(clinic_id=clinic_id, user_id=user_id)

    today = timezone.localdate()
    roles = active_membership_roles_for_users(
        clinic_id=clinic_id, user_ids=unique_participants, on_date=today
    )
    missing = [uid for uid in unique_participants if uid not in roles]
    if missing:
        raise ValidationError("Há participantes sem vínculo ativo nesta clínica.")

    if kind == ConversationKind.CLINICAL:
        _validate_clinical_links(clinic_id=clinic_id, roles=roles, on_date=today)

    conversation = Conversation.infrastructure_objects.create(
        clinic_id=clinic_id,
        kind=kind,
        subject=subject.strip(),
        created_by_id=actor.pk,
        is_active=True,
    )
    for user_id in unique_participants:
        ConversationParticipant.infrastructure_objects.create(
            clinic_id=clinic_id,
            conversation_id=conversation.pk,
            user_id=user_id,
            is_active=True,
        )
    conversation_created.send(
        sender=Conversation,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(conversation.pk),
        request_id=request_id,
    )
    return conversation


@transaction.atomic
def send_message(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    conversation_id: UUID,
    body: str,
    request_id: UUID,
) -> Message:
    """Append one immutable message from an active participant (8.8.4.2)."""
    participant = ConversationParticipant.infrastructure_objects.filter(
        clinic_id=clinic_id,
        conversation_id=conversation_id,
        user_id=actor.pk,
        is_active=True,
    ).first()
    if participant is None:
        raise PermissionDenied
    clean_body = body.strip()
    if not clean_body:
        raise ValidationError("A mensagem não pode estar vazia.")

    message = Message.infrastructure_objects.create(
        clinic_id=clinic_id,
        conversation_id=conversation_id,
        sender_id=actor.pk,
        body=clean_body,
    )
    # Neutral delivery records for every other active participant, no content.
    recipients = ConversationParticipant.infrastructure_objects.filter(
        clinic_id=clinic_id,
        conversation_id=conversation_id,
        is_active=True,
    ).exclude(user_id=actor.pk)
    for recipient in recipients:
        NotificationEvent.infrastructure_objects.create(
            clinic_id=clinic_id,
            recipient_id=recipient.user_id,
            kind=NotificationEvent.Kind.NEW_MESSAGE,
            channel=ReminderChannel.PUSH,
            status=NotificationStatus.QUEUED,
            correlation_id=str(message.pk),
        )
    message_sent.send(
        sender=Message,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(message.pk),
        request_id=request_id,
    )
    return message


@transaction.atomic
def mark_conversation_read(
    *, clinic_id: UUID, actor: AbstractBaseUser, conversation_id: UUID
) -> int:
    """Create idempotent read receipts for every unseen message in one conversation."""
    participant = ConversationParticipant.infrastructure_objects.filter(
        clinic_id=clinic_id,
        conversation_id=conversation_id,
        user_id=actor.pk,
        is_active=True,
    ).first()
    if participant is None:
        raise PermissionDenied

    already_read = set(
        MessageReadReceipt.infrastructure_objects.filter(
            clinic_id=clinic_id,
            participant_id=participant.pk,
        ).values_list("message_id", flat=True)
    )
    unread = Message.infrastructure_objects.filter(
        clinic_id=clinic_id, conversation_id=conversation_id
    ).exclude(pk__in=already_read)
    created = 0
    for message in unread:
        MessageReadReceipt.infrastructure_objects.create(
            clinic_id=clinic_id,
            message_id=message.pk,
            participant_id=participant.pk,
        )
        created += 1
    return created


def _scan_or_quarantine(upload: UploadedFile) -> ScanStatus:
    """Run the configured scanner when present; otherwise stay quarantined."""
    command = getattr(settings, "PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND", ())
    if command:
        require_clean_malware_scan(upload)
        return ScanStatus.CLEAN
    return ScanStatus.QUARANTINED


@transaction.atomic
def add_attachment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    message_id: UUID,
    upload: UploadedFile,
    request_id: UUID,
) -> MessageAttachment:
    """Attach one validated, quarantined file to a message the actor sent (8.8.5.1)."""
    message = Message.infrastructure_objects.filter(
        pk=message_id, clinic_id=clinic_id
    ).first()
    if message is None or message.sender_id != actor.pk:
        raise PermissionDenied

    policy = PrivateUploadPolicy()
    metadata = policy.validate(upload)
    upload.seek(0)
    attachment = MessageAttachment(
        clinic_id=clinic_id,
        message_id=message.pk,
        uploader_id=actor.pk,
        original_name=metadata.safe_name,
        content_type=metadata.detected_media_type,
        size_bytes=metadata.size,
        scan_status=ScanStatus.QUARANTINED,
    )
    attachment.file.save(metadata.safe_name, upload, save=False)
    attachment.scan_status = _scan_or_quarantine(upload)
    attachment.save(force_insert=True)
    attachment_uploaded.send(
        sender=MessageAttachment,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(attachment.pk),
        request_id=request_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="create",
        resource_type="message_attachment",
        resource_id=str(attachment.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return attachment


@transaction.atomic
def download_attachment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    attachment_id: UUID,
    request_id: UUID,
) -> MessageAttachment:
    """Authorize and return one clean attachment for download (8.8.5.2/8.8.5.4)."""
    attachment = (
        MessageAttachment.infrastructure_objects.select_related("message__conversation")
        .filter(pk=attachment_id, clinic_id=clinic_id)
        .first()
    )
    if attachment is None:
        raise PermissionDenied
    participant = ConversationParticipant.infrastructure_objects.filter(
        clinic_id=clinic_id,
        conversation_id=attachment.message.conversation_id,
        user_id=actor.pk,
        is_active=True,
    ).first()
    if participant is None:
        raise PermissionDenied
    if attachment.scan_status != ScanStatus.CLEAN:
        raise PermissionDenied(
            "O anexo ainda não foi aprovado na varredura de segurança."
        )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="view",
        resource_type="message_attachment",
        resource_id=str(attachment.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    return attachment


@transaction.atomic
def delete_attachment(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    attachment_id: UUID,
    request_id: UUID,
) -> None:
    """Delete one attachment (uploader or clinic admin) and audit it (8.8.5.4)."""
    attachment = MessageAttachment.infrastructure_objects.filter(
        pk=attachment_id, clinic_id=clinic_id
    ).first()
    if attachment is None:
        raise PermissionDenied
    is_uploader = attachment.uploader_id == actor.pk
    is_admin = has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    )
    if not is_uploader and not is_admin:
        raise PermissionDenied
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="delete",
        resource_type="message_attachment",
        resource_id=str(attachment.pk),
        outcome="success",
        request_id=request_id,
        network_origin=None,
    )
    attachment.file.delete(save=False)
    attachment.delete()
