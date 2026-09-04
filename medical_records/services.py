"""Services for clinical episodes, record entries, versions and addenda (8.18.1)."""

from __future__ import annotations

import hashlib
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService
from medical_records.contracts import (
    AddendumReason,
    EpisodeStatus,
    PurposeOfUse,
    RecordEntryStatus,
    RecordEntryType,
)
from medical_records.entry_models import (
    ClinicalEpisode,
    MedicalRecordEntry,
    RecordAddendum,
    RecordEntryVersion,
)
from medical_records.events import (
    addendum_created,
    episode_created,
    record_entry_created,
    record_entry_signed,
    record_entry_updated,
)
from medical_records.policies import (
    can_create_addendum,
    can_edit_record_entry,
    can_sign_record_entry,
)


class Service(CoreService[Any, Any]):
    """Medical records domain service base."""


def _compute_entry_hash(entry: MedicalRecordEntry) -> str:
    """Compute SHA-256 hash of the canonical entry content."""
    canonical = (
        f"{entry.title}|{entry.content}|"
        f"{entry.objective_data}|{entry.current_version}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _compute_addendum_hash(addendum: RecordAddendum) -> str:
    canonical = f"{addendum.entry_id}|{addendum.addendum_number}|{addendum.content}"
    return hashlib.sha256(canonical.encode()).hexdigest()


@transaction.atomic
def create_clinical_episode(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    professional_user: AbstractBaseUser,
    title: str,
    summary: str = "",
    request_id: str | None = None,
    network_origin: str = "internal",
) -> ClinicalEpisode:
    """Create a new clinical episode grouping care encounters."""
    episode = ClinicalEpisode.objects.create(
        clinic_id=clinic_id,
        patient_id=patient_id,
        attending_professional=cast(Any, professional_user),
        title=title,
        summary=summary,
        status=EpisodeStatus.ACTIVE.value,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=professional_user.pk,
        action="clinical_episode.created",
        resource_type="ClinicalEpisode",
        resource_id=str(episode.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    episode_created.send(sender=ClinicalEpisode, episode=episode)
    return episode


@transaction.atomic
def create_record_entry_draft(
    *,
    clinic_id: UUID,
    patient_id: UUID,
    author_user: AbstractBaseUser,
    title: str,
    content: str,
    entry_type: str = RecordEntryType.CLINICAL_EVOLUTION.value,
    purpose_of_use: str = PurposeOfUse.CARE_DELIVERY.value,
    episode_id: UUID | None = None,
    is_administrative: bool = False,
    objective_data: dict[str, Any] | None = None,
    plan_and_conduct: str = "",
    diagnostic_hypotheses: str = "",
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordEntry:
    """Create a new medical record entry in DRAFT status."""
    entry = MedicalRecordEntry.objects.create(
        clinic_id=clinic_id,
        patient_id=patient_id,
        author=cast(Any, author_user),
        title=title,
        content=content,
        entry_type=entry_type,
        purpose_of_use=purpose_of_use,
        episode_id=episode_id,
        is_administrative=is_administrative,
        objective_data=objective_data or {},
        plan_and_conduct=plan_and_conduct,
        diagnostic_hypotheses=diagnostic_hypotheses,
        status=RecordEntryStatus.DRAFT.value,
        current_version=1,
        lock_version=1,
    )
    entry.content_hash = _compute_entry_hash(entry)
    entry.save(update_fields=["content_hash"])

    # Preserve initial version snapshot
    RecordEntryVersion.objects.create(
        clinic_id=clinic_id,
        entry=entry,
        version_number=1,
        author=cast(Any, author_user),
        title=title,
        content=content,
        objective_data=objective_data or {},
        plan_and_conduct=plan_and_conduct,
        diagnostic_hypotheses=diagnostic_hypotheses,
        content_hash=entry.content_hash,
        reason_for_change="Initial draft",
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=author_user.pk,
        action="record_entry.created",
        resource_type="MedicalRecordEntry",
        resource_id=str(entry.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    record_entry_created.send(sender=MedicalRecordEntry, entry=entry)
    return entry


@transaction.atomic
def update_record_entry_draft(
    *,
    entry: MedicalRecordEntry,
    editor_user: AbstractBaseUser,
    title: str | None = None,
    content: str | None = None,
    objective_data: dict[str, Any] | None = None,
    plan_and_conduct: str | None = None,
    diagnostic_hypotheses: str | None = None,
    reason_for_change: str = "",
    expected_lock_version: int,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordEntry:
    """Update a DRAFT entry with optimistic concurrency control."""
    if not can_edit_record_entry(user=editor_user, entry=entry):
        raise PermissionError("User cannot edit this record entry.")
    if entry.lock_version != expected_lock_version:
        raise ValueError(
            f"Optimistic lock conflict: expected version {expected_lock_version}, "
            f"got {entry.lock_version}."
        )
    # Apply updates
    if title is not None:
        entry.title = title
    if content is not None:
        entry.content = content
    if objective_data is not None:
        entry.objective_data = objective_data
    if plan_and_conduct is not None:
        entry.plan_and_conduct = plan_and_conduct
    if diagnostic_hypotheses is not None:
        entry.diagnostic_hypotheses = diagnostic_hypotheses

    entry.current_version += 1
    entry.lock_version += 1
    entry.content_hash = _compute_entry_hash(entry)
    entry.save(
        update_fields=[
            "title", "content", "objective_data", "plan_and_conduct",
            "diagnostic_hypotheses", "current_version", "lock_version",
            "content_hash", "updated_at",
        ]
    )
    # Save immutable version snapshot
    RecordEntryVersion.objects.create(
        clinic_id=entry.clinic_id,
        entry=entry,
        version_number=entry.current_version,
        author=cast(Any, editor_user),
        title=entry.title,
        content=entry.content,
        objective_data=entry.objective_data,
        plan_and_conduct=entry.plan_and_conduct,
        diagnostic_hypotheses=entry.diagnostic_hypotheses,
        content_hash=entry.content_hash,
        reason_for_change=reason_for_change,
    )
    record_audit_event(
        clinic_id=entry.clinic_id,
        actor_id=editor_user.pk,
        action="record_entry.updated",
        resource_type="MedicalRecordEntry",
        resource_id=str(entry.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    record_entry_updated.send(sender=MedicalRecordEntry, entry=entry)
    return entry


@transaction.atomic
def sign_record_entry(
    *,
    entry: MedicalRecordEntry,
    signing_user: AbstractBaseUser,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordEntry:
    """Sign a record entry, making it immutable (8.18.1, 8.18.3)."""
    if not can_sign_record_entry(user=signing_user, entry=entry):
        raise PermissionError("User is not authorized to sign this record entry.")
    entry.status = RecordEntryStatus.SIGNED.value
    entry.signed_at = timezone.now()
    entry.signed_by = cast(Any, signing_user)
    entry.save(update_fields=["status", "signed_at", "signed_by", "updated_at"])
    record_audit_event(
        clinic_id=entry.clinic_id,
        actor_id=signing_user.pk,
        action="record_entry.signed",
        resource_type="MedicalRecordEntry",
        resource_id=str(entry.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    record_entry_signed.send(sender=MedicalRecordEntry, entry=entry)
    return entry


@transaction.atomic
def create_record_addendum(
    *,
    entry: MedicalRecordEntry,
    author_user: AbstractBaseUser,
    content: str,
    reason: str = AddendumReason.SUPPLEMENTAL_INFO.value,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> RecordAddendum:
    """Create a formal signed addendum to an immutable entry (8.18.1)."""
    if not can_create_addendum(user=author_user, entry=entry):
        raise PermissionError(
            "Cannot create addendum: entry not signed or user not authorized."
        )
    existing_count = RecordAddendum.infrastructure_objects.filter(
        entry=entry
    ).count()
    addendum = RecordAddendum.objects.create(
        clinic_id=entry.clinic_id,
        entry=entry,
        author=cast(Any, author_user),
        addendum_number=existing_count + 1,
        reason=reason,
        content=content,
        content_hash="",
        is_signed=False,
    )
    addendum.content_hash = _compute_addendum_hash(addendum)
    addendum.signed_at = timezone.now()
    addendum.signed_by = cast(Any, author_user)
    addendum.is_signed = True
    addendum.save(
        update_fields=["content_hash", "signed_at", "signed_by", "is_signed"]
    )
    # Mark parent entry as AMENDED
    if entry.status == RecordEntryStatus.SIGNED.value:
        entry.status = RecordEntryStatus.AMENDED.value
        entry.save(update_fields=["status", "updated_at"])
    record_audit_event(
        clinic_id=entry.clinic_id,
        actor_id=author_user.pk,
        action="record_entry.addendum_created",
        resource_type="RecordAddendum",
        resource_id=str(addendum.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    addendum_created.send(sender=RecordAddendum, addendum=addendum)
    return addendum
