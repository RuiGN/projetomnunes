"""Authorization policies for medical records, documents and retention (8.18)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy
from medical_records.contracts import RecordEntryStatus
from medical_records.entry_models import MedicalRecordEntry
from medical_records.governance_models import MedicalRecordsRolloutFlag
from medical_records.retention_models import DisposalBatch


def _is_clinical_professional(*, user_id: UUID, clinic_id: UUID) -> bool:
    today = timezone.localdate()
    return any(
        has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            on_date=today,
        )
        for role in {"therapist", "physician", "clinical_director"}
    )


def _is_clinic_admin(*, user_id: UUID, clinic_id: UUID) -> bool:
    today = timezone.localdate()
    return has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=user_id,
        role="clinic_admin",
        on_date=today,
    )


def _emergency_read_only(*, clinic_id: UUID) -> bool:
    flag = MedicalRecordsRolloutFlag.infrastructure_objects.filter(
        clinic_id=clinic_id
    ).first()
    return bool(flag and flag.emergency_read_only_mode)


class AuthorizationPolicy(CoreAuthorizationPolicy[AbstractBaseUser, Any]):
    """Medical records domain baseline authorization policy."""

    def is_allowed(self, subject: AbstractBaseUser, resource: Any, /) -> bool:
        if not subject.is_authenticated or not subject.is_active:
            return False
        clinic_id = getattr(resource, "clinic_id", None)
        if clinic_id is None:
            return False
        today = timezone.localdate()
        return any(
            has_active_clinic_role(
                clinic_id=clinic_id,
                user_id=subject.pk,
                role=role,
                on_date=today,
            )
            for role in {"clinic_admin", "therapist", "physician", "clinical_director"}
        )


def can_view_medical_record(
    *,
    user: AbstractBaseUser,
    entry: MedicalRecordEntry,
) -> bool:
    """Check if user can read a patient's medical record entry."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _is_clinical_professional(
        user_id=user.pk, clinic_id=entry.clinic_id
    ) or _is_clinic_admin(user_id=user.pk, clinic_id=entry.clinic_id)


def can_edit_record_entry(
    *,
    user: AbstractBaseUser,
    entry: MedicalRecordEntry,
) -> bool:
    """Allow edits only on DRAFT entries by the original author."""
    if not user.is_authenticated or not user.is_active:
        return False
    if _emergency_read_only(clinic_id=entry.clinic_id):
        return False
    if entry.status != RecordEntryStatus.DRAFT.value:
        return False
    return bool(entry.author_id == user.pk)


def can_sign_record_entry(
    *,
    user: AbstractBaseUser,
    entry: MedicalRecordEntry,
) -> bool:
    """Allow signing only by clinical professionals on their own draft entries."""
    if not user.is_authenticated or not user.is_active:
        return False
    if _emergency_read_only(clinic_id=entry.clinic_id):
        return False
    if entry.status not in (
        RecordEntryStatus.DRAFT.value,
        RecordEntryStatus.IN_REVIEW.value,
    ):
        return False
    return (
        entry.author_id == user.pk
        and _is_clinical_professional(user_id=user.pk, clinic_id=entry.clinic_id)
    )


def can_create_addendum(
    *,
    user: AbstractBaseUser,
    entry: MedicalRecordEntry,
) -> bool:
    """Allow addenda only on SIGNED/AMENDED entries by clinical professionals."""
    if not user.is_authenticated or not user.is_active:
        return False
    if _emergency_read_only(clinic_id=entry.clinic_id):
        return False
    if entry.status not in (
        RecordEntryStatus.SIGNED.value,
        RecordEntryStatus.AMENDED.value,
    ):
        return False
    return _is_clinical_professional(user_id=user.pk, clinic_id=entry.clinic_id)


def can_upload_document(
    *,
    user: AbstractBaseUser,
    clinic_id: UUID,
) -> bool:
    """Check if user may upload a document to the clinic."""
    if not user.is_authenticated or not user.is_active:
        return False
    if _emergency_read_only(clinic_id=clinic_id):
        return False
    return _is_clinical_professional(
        user_id=user.pk, clinic_id=clinic_id
    ) or _is_clinic_admin(user_id=user.pk, clinic_id=clinic_id)


def can_institute_legal_hold(
    *,
    user: AbstractBaseUser,
    clinic_id: UUID,
) -> bool:
    """Only clinic admins or legal officers may institute a legal hold."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _is_clinic_admin(user_id=user.pk, clinic_id=clinic_id)


def can_approve_disposal(
    *,
    user: AbstractBaseUser,
    batch: DisposalBatch,
) -> bool:
    """Dual-approval: approver must differ from requester and must be a clinic admin."""
    if not user.is_authenticated or not user.is_active:
        return False
    if batch.requested_by_id == user.pk:
        # Segregation of duties: requester cannot self-approve
        return False
    return _is_clinic_admin(user_id=user.pk, clinic_id=batch.clinic_id)
