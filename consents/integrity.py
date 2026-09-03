"""Canonical integrity verification for published consent documents."""

from __future__ import annotations

import hashlib
import hmac
import json

from django.core.exceptions import ValidationError

from .models import ConsentDocument


class ConsentDocumentIntegrityError(ValidationError):
    """Raised when a published document differs from its canonical hash."""


def publication_payload(document: ConsentDocument) -> bytes:
    """Serialize every immutable publication field deterministically."""
    payload = {
        "alternative_instructions": document.alternative_instructions,
        "audience": document.audience,
        "clinic_contact_instructions": document.clinic_contact_instructions,
        "clinic_id": str(document.clinic_id),
        "content": document.content,
        "document_id": str(document.pk),
        "document_type": document.document_type,
        "effective_from": document.effective_from.isoformat(),
        "effective_until": (
            document.effective_until.isoformat()
            if document.effective_until is not None
            else None
        ),
        "is_active": document.is_active,
        "is_mandatory": document.is_mandatory,
        "published_at": (
            document.published_at.isoformat()
            if document.published_at is not None
            else None
        ),
        "published_by_id": str(document.published_by_id),
        "purpose": document.purpose,
        "refusal_consequence": document.refusal_consequence,
        "title": document.title,
        "version": document.version,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def expected_publication_hash(document: ConsentDocument) -> str:
    """Calculate the digest expected from persisted canonical fields."""
    return hashlib.sha256(publication_payload(document)).hexdigest()


def require_document_integrity(document: ConsentDocument) -> None:
    """Fail closed using a timing-safe comparison before document use."""
    expected = expected_publication_hash(document)
    if not hmac.compare_digest(expected, document.publication_hash):
        raise ConsentDocumentIntegrityError(
            "A integridade do documento publicado não pôde ser confirmada."
        )


__all__ = [
    "ConsentDocumentIntegrityError",
    "expected_publication_hash",
    "publication_payload",
    "require_document_integrity",
]
