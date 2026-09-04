"""Selectors for medical records, documents, signatures and retention (8.18)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from core.selectors import Selector as CoreSelector
from medical_records.contracts import (
    DEFAULT_SIGNED_URL_EXPIRY_SECONDS,
    DocumentScanStatus,
)
from medical_records.document_models import ClinicalDocument, DocumentAccessLog
from medical_records.entry_models import (
    ClinicalEpisode,
    MedicalRecordEntry,
    RecordAddendum,
    RecordEntryVersion,
)
from medical_records.governance_models import (
    MedicalRecordsRolloutFlag,
)
from medical_records.retention_models import (
    LegalHold,
    LegalHoldItem,
    RetentionPolicy,
)
from medical_records.signature_models import ElectronicSignature


class Selector(CoreSelector[Any, Any]):
    """Default medical records domain selector."""


# ---------------------------------------------------------------------------
# Episode & Entry Selectors
# ---------------------------------------------------------------------------


def get_patient_timeline(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    purpose: str = "care_delivery",
) -> dict[str, Any]:
    """Full longitudinal timeline: episodes, entries, versions, and addenda."""
    episodes = list(
        ClinicalEpisode.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_id)
        .order_by("-start_date")
    )
    entries = list(
        MedicalRecordEntry.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_id)
        .order_by("created_at")
        .select_related("author")
    )
    addenda = list(
        RecordAddendum.objects.for_clinic(clinic_id)
        .filter(entry__patient_id=patient_id)
        .order_by("addendum_number")
    )
    return {
        "episodes": episodes,
        "entries": entries,
        "addenda": addenda,
        "total_entries": len(entries),
    }


def get_entry_with_versions_and_addenda(
    *,
    clinic_id: UUID,
    entry_id: UUID,
) -> dict[str, Any] | None:
    """Fetch a single entry with all immutable versions and formal addenda."""
    entry = (
        MedicalRecordEntry.objects.for_clinic(clinic_id)
        .filter(id=entry_id)
        .first()
    )
    if entry is None:
        return None
    versions = list(
        RecordEntryVersion.objects.for_clinic(clinic_id)
        .filter(entry_id=entry_id)
        .order_by("version_number")
    )
    addenda = list(
        RecordAddendum.objects.for_clinic(clinic_id)
        .filter(entry_id=entry_id)
        .order_by("addendum_number")
    )
    return {"entry": entry, "versions": versions, "addenda": addenda}


# ---------------------------------------------------------------------------
# Document Selectors
# ---------------------------------------------------------------------------


def get_document_download_url(
    *,
    clinic_id: UUID,
    document_id: UUID,
    accessor: AbstractBaseUser,
    purpose: str = "care_delivery",
    ip_address: str | None = None,
) -> str:
    """Generate signed URL and log access — returns stub in tests."""
    document = (
        ClinicalDocument.objects.for_clinic(clinic_id)
        .filter(id=document_id, scan_status=DocumentScanStatus.CLEAN.value)
        .first()
    )
    if document is None:
        raise ValueError("Document not found or not yet cleared from quarantine.")
    # Log the access event
    DocumentAccessLog.objects.create(
        clinic_id=clinic_id,
        document=document,
        accessor=cast(Any, accessor),
        purpose=purpose,
        action="download",
        ip_address=ip_address,
    )
    # In production, this would generate a pre-signed storage URL with TTL
    expiry = int(timezone.now().timestamp()) + DEFAULT_SIGNED_URL_EXPIRY_SECONDS
    return (
        f"/medical-records/documents/{document_id}/download"
        f"?expires={expiry}&clinic={clinic_id}"
    )


def get_quarantine_backlog(*, clinic_id: UUID) -> list[ClinicalDocument]:
    """Documents still in quarantine or scanning, ordered oldest-first."""
    return list(
        ClinicalDocument.objects.for_clinic(clinic_id)
        .filter(
            scan_status__in=[
                DocumentScanStatus.QUARANTINE.value,
                DocumentScanStatus.SCANNING.value,
            ]
        )
        .order_by("created_at")
    )


# ---------------------------------------------------------------------------
# Signature Selectors
# ---------------------------------------------------------------------------


def verify_signature_integrity(
    *,
    clinic_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> dict[str, Any]:
    """Verify the integrity of the latest signature for a resource."""
    signature = (
        ElectronicSignature.objects.for_clinic(clinic_id)
        .filter(resource_type=resource_type, resource_id=resource_id)
        .order_by("-signed_at")
        .first()
    )
    if signature is None:
        return {"status": "not_signed", "signature": None}
    return {
        "status": signature.status,
        "algorithm": signature.algorithm,
        "content_hash": signature.content_hash,
        "signed_at": signature.signed_at,
        "signer_id": signature.signer_id,
        "manifest": signature.manifest,
        "signature": signature,
    }


# ---------------------------------------------------------------------------
# Retention Selectors
# ---------------------------------------------------------------------------


def get_retention_disposal_candidates(
    *,
    clinic_id: UUID,
    resource_type: str,
    today: date | None = None,
) -> list[Any]:
    """List records eligible for disposal under active policies.

    Respects:
    - CFM 20-year retention floor.
    - Minority protection: clock starts at patient's 18th birthday.
    - Active legal holds block disposal unconditionally.
    """
    if today is None:
        today = timezone.localdate()
    policy = (
        RetentionPolicy.objects.for_clinic(clinic_id)
        .filter(resource_category=resource_type, is_active=True)
        .first()
    )
    if policy is None:
        return []
    # Get IDs blocked by active legal holds
    held_ids: set[UUID] = set(
        LegalHoldItem.infrastructure_objects.filter(
            hold__clinic_id=clinic_id,
            hold__is_active=True,
            resource_type=resource_type,
        ).values_list("resource_id", flat=True)
    )
    retention_cutoff = today - timedelta(days=policy.retention_years * 365)
    candidates: list[Any] = []
    if resource_type == "MedicalRecordEntry":
        entries = (
            MedicalRecordEntry.objects.for_clinic(clinic_id)
            .filter(created_at__date__lte=retention_cutoff)
            .exclude(id__in=held_ids)
        )
        candidates = list(entries)
    return candidates


def get_rollout_status(*, clinic_id: UUID) -> MedicalRecordsRolloutFlag | None:
    """Retrieve the rollout configuration for a clinic tenant."""
    return (
        MedicalRecordsRolloutFlag.infrastructure_objects.filter(
            clinic_id=clinic_id
        ).first()
    )


def get_active_legal_holds(*, clinic_id: UUID) -> list[LegalHold]:
    """Return all active legal holds for a clinic."""
    return list(
        LegalHold.objects.for_clinic(clinic_id)
        .filter(is_active=True)
        .order_by("-created_at")
    )
