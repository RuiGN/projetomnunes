"""Services for regulated retention, legal hold, and secure disposal (8.18.4)."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from medical_records.contracts import (
    DEFAULT_CLINICAL_RETENTION_YEARS,
    DisposalAction,
    DisposalBatchStatus,
    LegalBaseRetention,
    RetentionTrigger,
)
from medical_records.events import (
    disposal_batch_approved,
    disposal_batch_created,
    disposal_batch_executed,
    disposal_certificate_issued,
    legal_hold_instituted,
    legal_hold_released,
)
from medical_records.policies import can_approve_disposal, can_institute_legal_hold
from medical_records.retention_models import (
    DisposalBatch,
    DisposalCertificate,
    DisposalItem,
    LegalHold,
    LegalHoldItem,
    RetentionPolicy,
)


@transaction.atomic
def create_retention_policy(
    *,
    clinic_id: UUID,
    name: str,
    resource_category: str,
    retention_years: int = DEFAULT_CLINICAL_RETENTION_YEARS,
    retention_trigger: str = RetentionTrigger.EPISODE_END_DATE.value,
    legal_base: str = LegalBaseRetention.CFM_RES_1821_2007.value,
    disposal_action: str = DisposalAction.SECURE_DESTRUCTION.value,
    applies_to_minors: bool = True,
    policy_owner_role: str = "",
    notes: str = "",
    created_by_user: AbstractBaseUser | None = None,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> RetentionPolicy:
    """Register a versioned retention policy entry in the regulatory matrix."""
    existing_count = RetentionPolicy.infrastructure_objects.filter(
        clinic_id=clinic_id,
        resource_category=resource_category,
        is_active=True,
    ).count()
    policy = RetentionPolicy.objects.create(
        clinic_id=clinic_id,
        name=name,
        resource_category=resource_category,
        retention_years=retention_years,
        retention_trigger=retention_trigger,
        legal_base=legal_base,
        disposal_action=disposal_action,
        applies_to_minors=applies_to_minors,
        policy_version=existing_count + 1,
        policy_owner_role=policy_owner_role,
        notes=notes,
        is_active=True,
    )
    if created_by_user:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=created_by_user.pk,
            action="retention_policy.created",
            resource_type="RetentionPolicy",
            resource_id=str(policy.id),
            outcome="success",
            request_id=uuid4(),
            network_origin=network_origin,
        )
    return policy


@transaction.atomic
def institute_legal_hold(
    *,
    clinic_id: UUID,
    requesting_user: AbstractBaseUser,
    hold_reference: str,
    reason: str,
    scope_description: str,
    resource_pairs: list[tuple[str, UUID]],
    review_due_date: date | None = None,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> LegalHold:
    """Freeze records from disposal for legal/investigative reasons (8.18.4)."""
    if not can_institute_legal_hold(user=requesting_user, clinic_id=clinic_id):
        raise PermissionError("User is not authorized to institute a legal hold.")
    hold = LegalHold.objects.create(
        clinic_id=clinic_id,
        hold_reference=hold_reference,
        reason=reason,
        scope_description=scope_description,
        requested_by=cast(Any, requesting_user),
        is_active=True,
        review_due_date=review_due_date,
    )
    for resource_type, resource_id in resource_pairs:
        LegalHoldItem.objects.create(
            hold=hold,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=requesting_user.pk,
        action="legal_hold.instituted",
        resource_type="LegalHold",
        resource_id=str(hold.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    legal_hold_instituted.send(sender=LegalHold, hold=hold)
    return hold


@transaction.atomic
def release_legal_hold(
    *,
    hold: LegalHold,
    releasing_user: AbstractBaseUser,
    release_reason: str,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> LegalHold:
    """Release an active legal hold after judicial or administrative clearance."""
    if not hold.is_active:
        raise ValueError("Legal hold is already released.")
    hold.is_active = False
    hold.released_at = timezone.now()
    hold.released_by = cast(Any, releasing_user)
    hold.release_reason = release_reason
    hold.save(
        update_fields=["is_active", "released_at", "released_by", "release_reason"]
    )
    record_audit_event(
        clinic_id=hold.clinic_id,
        actor_id=releasing_user.pk,
        action="legal_hold.released",
        resource_type="LegalHold",
        resource_id=str(hold.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    legal_hold_released.send(sender=LegalHold, hold=hold)
    return hold


@transaction.atomic
def create_disposal_batch(
    *,
    clinic_id: UUID,
    requesting_user: AbstractBaseUser,
    batch_reference: str,
    disposal_action: str,
    justification: str,
    resource_pairs: list[tuple[str, UUID]],
    request_id: str | None = None,
    network_origin: str = "internal",
) -> DisposalBatch:
    """Request a controlled disposal batch requiring a separate approver (8.18.4)."""
    # Check legal holds for every item before creating the batch
    held_ids: set[UUID] = set(
        LegalHoldItem.infrastructure_objects.filter(
            hold__clinic_id=clinic_id,
            hold__is_active=True,
        ).values_list("resource_id", flat=True)
    )
    batch = DisposalBatch.objects.create(
        clinic_id=clinic_id,
        batch_reference=batch_reference,
        requested_by=cast(Any, requesting_user),
        status=DisposalBatchStatus.PENDING_REVIEW.value,
        disposal_action=disposal_action,
        justification=justification,
        items_count=len(resource_pairs),
    )
    for resource_type, resource_id in resource_pairs:
        DisposalItem.objects.create(
            batch=batch,
            resource_type=resource_type,
            resource_id=resource_id,
            has_legal_hold=(resource_id in held_ids),
        )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=requesting_user.pk,
        action="disposal_batch.created",
        resource_type="DisposalBatch",
        resource_id=str(batch.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    disposal_batch_created.send(sender=DisposalBatch, batch=batch)
    return batch


@transaction.atomic
def approve_disposal_batch(
    *,
    batch: DisposalBatch,
    approving_user: AbstractBaseUser,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> DisposalBatch:
    """Dual-approval: a different user approves the disposal batch (8.18.4)."""
    if not can_approve_disposal(user=approving_user, batch=batch):
        raise PermissionError(
            "User cannot approve this batch (either unauthorized or is the requester)."
        )
    if batch.status != DisposalBatchStatus.PENDING_REVIEW.value:
        raise ValueError(f"Batch status '{batch.status}' is not pending review.")
    # Re-check for legal holds before approval
    held_ids: set[UUID] = set(
        LegalHoldItem.infrastructure_objects.filter(
            hold__clinic_id=batch.clinic_id,
            hold__is_active=True,
        ).values_list("resource_id", flat=True)
    )
    held_count = batch.items.filter(resource_id__in=held_ids).update(
        has_legal_hold=True
    )
    if held_count > 0:
        raise ValueError(
            f"{held_count} item(s) in this batch are protected by an active legal hold."
        )
    batch.status = DisposalBatchStatus.APPROVED.value
    batch.approved_by = cast(Any, approving_user)
    batch.approved_at = timezone.now()
    batch.save(update_fields=["status", "approved_by", "approved_at"])
    record_audit_event(
        clinic_id=batch.clinic_id,
        actor_id=approving_user.pk,
        action="disposal_batch.approved",
        resource_type="DisposalBatch",
        resource_id=str(batch.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    disposal_batch_approved.send(sender=DisposalBatch, batch=batch)
    return batch


@transaction.atomic
def execute_disposal_batch(
    *,
    batch: DisposalBatch,
    executing_user: AbstractBaseUser,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> DisposalCertificate:
    """Execute approved disposal and issue a cryptographic certificate (8.18.4)."""
    if batch.status != DisposalBatchStatus.APPROVED.value:
        raise ValueError(
            f"Batch must be in APPROVED status to execute, got '{batch.status}'."
        )
    batch.status = DisposalBatchStatus.EXECUTING.value
    batch.save(update_fields=["status"])

    processed = 0
    item_ids: list[str] = []
    for item in batch.items.filter(processed=False, has_legal_hold=False):
        # Idempotent: mark processed without actual data deletion in this stub
        item.processed = True
        item.processed_at = timezone.now()
        item.save(update_fields=["processed", "processed_at"])
        item_ids.append(str(item.resource_id))
        processed += 1

    batch.status = DisposalBatchStatus.COMPLETED.value
    batch.executed_at = timezone.now()
    batch.items_processed = processed
    batch.save(update_fields=["status", "executed_at", "items_processed"])

    # Issue disposal certificate — no clinical data exposed
    items_hash = hashlib.sha256(
        "|".join(sorted(item_ids)).encode()
    ).hexdigest()
    certificate_text = (
        f"Certificate of Disposal\n"
        f"Batch: {batch.batch_reference}\n"
        f"Clinic: {batch.clinic_id}\n"
        f"Items processed: {processed}\n"
        f"Items hash (SHA-256): {items_hash}\n"
        f"Legal basis: CFM Res. 1821/2007 / LGPD\n"
        f"Executed at: {batch.executed_at.isoformat()}\n"
        f"Executed by: {executing_user.pk}\n"
    )
    certificate = DisposalCertificate.objects.create(
        batch=batch,
        issued_by=cast(Any, executing_user),
        items_hash=items_hash,
        legal_base=LegalBaseRetention.CFM_RES_1821_2007.value,
        certificate_text=certificate_text,
    )
    record_audit_event(
        clinic_id=batch.clinic_id,
        actor_id=executing_user.pk,
        action="disposal_batch.executed",
        resource_type="DisposalBatch",
        resource_id=str(batch.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    disposal_batch_executed.send(sender=DisposalBatch, batch=batch)
    disposal_certificate_issued.send(
        sender=DisposalCertificate, certificate=certificate
    )
    return certificate
