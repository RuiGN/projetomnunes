"""Services for document upload, quarantine, scanning and access (8.18.2)."""

from __future__ import annotations

import hashlib
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from medical_records.contracts import (
    ALLOWED_DOCUMENT_MIME_TYPES,
    MAX_DOCUMENT_SIZE_BYTES,
    ConfidentialityLevel,
    DocumentScanStatus,
    DocumentType,
)
from medical_records.document_models import ClinicalDocument
from medical_records.events import (
    document_promoted,
    document_rejected,
    document_scan_completed,
    document_uploaded_to_quarantine,
)
from medical_records.policies import can_upload_document

_BLOCKED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "application/javascript",
        "application/x-sh",
        "application/x-executable",
        "application/x-msdos-program",
    }
)


def _validate_upload(
    *,
    file_name: str,
    mime_type: str,
    file_size_bytes: int,
    content: bytes,
) -> None:
    """Validate file before accepting to quarantine."""
    if mime_type in _BLOCKED_MIME_TYPES:
        raise ValueError(f"MIME type '{mime_type}' is not permitted.")
    if mime_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise ValueError(
            f"Unsupported MIME type '{mime_type}'. "
            f"Allowed: {', '.join(ALLOWED_DOCUMENT_MIME_TYPES)}"
        )
    if file_size_bytes > MAX_DOCUMENT_SIZE_BYTES:
        raise ValueError(
            f"File size {file_size_bytes} exceeds the maximum of "
            f"{MAX_DOCUMENT_SIZE_BYTES} bytes."
        )
    if len(content) != file_size_bytes:
        raise ValueError("Content length does not match declared file_size_bytes.")
    # Detect polyglot by checking for embedded HTML/JS markers
    lowered = content[:4096].lower()
    if b"<script" in lowered or b"<!doctype html" in lowered:
        raise ValueError("File contains forbidden embedded active content.")


@transaction.atomic
def upload_document_to_quarantine(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    uploader_user: AbstractBaseUser,
    file_name: str,
    mime_type: str,
    file_size_bytes: int,
    content: bytes,
    document_type: str = DocumentType.MEDICAL_REPORT.value,
    title: str = "",
    description: str = "",
    confidentiality_level: str = ConfidentialityLevel.STANDARD.value,
    episode_id: UUID | None = None,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> ClinicalDocument:
    """Accept a document upload into quarantine after validation (8.18.2)."""
    if not can_upload_document(user=uploader_user, clinic_id=clinic_id):
        raise PermissionError("User is not authorized to upload documents.")
    _validate_upload(
        file_name=file_name,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        content=content,
    )
    sha256 = hashlib.sha256(content).hexdigest()
    storage_path = (
        f"clinic_{clinic_id}/patient_{patient_id}/docs/{sha256[:16]}/{sha256}.bin"
    )
    document = ClinicalDocument.objects.create(
        clinic_id=clinic_id,
        patient_id=patient_id,
        author=cast(Any, uploader_user),
        document_type=document_type,
        confidentiality_level=confidentiality_level,
        scan_status=DocumentScanStatus.QUARANTINE.value,
        title=title or file_name,
        description=description,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
        sha256_checksum=sha256,
        storage_path=storage_path,
        episode_id=episode_id,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=uploader_user.pk,
        action="document.uploaded_to_quarantine",
        resource_type="ClinicalDocument",
        resource_id=str(document.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    document_uploaded_to_quarantine.send(
        sender=ClinicalDocument, document=document
    )
    return document


@transaction.atomic
def complete_document_scan(
    *,
    document: ClinicalDocument,
    scan_clean: bool,
    scan_notes: str = "",
    promoted_by_user: AbstractBaseUser | None = None,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> ClinicalDocument:
    """Record the antivirus scan result and promote or reject the document."""
    document.scanned_at = timezone.now()
    document.scan_clean = scan_clean
    if scan_clean:
        document.scan_status = DocumentScanStatus.CLEAN.value
        if promoted_by_user is not None:
            document.approved_at = timezone.now()
            document.approved_by = cast(Any, promoted_by_user)
        action = "document.scan_clean_promoted"
    else:
        document.scan_status = DocumentScanStatus.REJECTED.value
        document.quarantine_reason = scan_notes
        action = "document.scan_rejected"
    document.save(
        update_fields=[
            "scan_status", "scan_clean", "scanned_at",
            "quarantine_reason", "approved_at", "approved_by",
        ]
    )
    actor_id = promoted_by_user.pk if promoted_by_user else getattr(
        document.author, "pk", None
    )
    record_audit_event(
        clinic_id=document.clinic_id,
        actor_id=actor_id,
        action=action,
        resource_type="ClinicalDocument",
        resource_id=str(document.id),
        outcome="success" if scan_clean else "rejected",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    signal = document_promoted if scan_clean else document_rejected
    signal.send(sender=ClinicalDocument, document=document)
    document_scan_completed.send(
        sender=ClinicalDocument, document=document, clean=scan_clean
    )
    return document
