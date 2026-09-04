"""Services for rollout control, emergency read-only mode and record export (8.18.5)."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from medical_records.contracts import ExportFormat, ExportStatus
from medical_records.events import (
    medical_record_export_requested,
    medical_records_read_only_activated,
    medical_records_read_only_deactivated,
)
from medical_records.governance_models import (
    MedicalRecordExportRequest,
    MedicalRecordsRolloutFlag,
)


@transaction.atomic
def get_or_create_rollout_flag(
    *,
    clinic_id: UUID,
) -> MedicalRecordsRolloutFlag:
    """Ensure a rollout flag record exists for the clinic tenant."""
    flag, _ = MedicalRecordsRolloutFlag.infrastructure_objects.get_or_create(
        clinic_id=clinic_id
    )
    return flag


@transaction.atomic
def update_rollout_flags(
    *,
    clinic_id: UUID,
    updating_user: AbstractBaseUser,
    records_enabled: bool | None = None,
    documents_enabled: bool | None = None,
    signatures_enabled: bool | None = None,
    retention_enforcement_enabled: bool | None = None,
    export_enabled: bool | None = None,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordsRolloutFlag:
    """Update feature enablement flags for a clinic tenant."""
    flag = get_or_create_rollout_flag(clinic_id=clinic_id)
    if records_enabled is not None:
        flag.records_enabled = records_enabled
    if documents_enabled is not None:
        flag.documents_enabled = documents_enabled
    if signatures_enabled is not None:
        flag.signatures_enabled = signatures_enabled
    if retention_enforcement_enabled is not None:
        flag.retention_enforcement_enabled = retention_enforcement_enabled
    if export_enabled is not None:
        flag.export_enabled = export_enabled
    flag.updated_by = cast(Any, updating_user)
    flag.save()
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=updating_user.pk,
        action="medical_records_rollout.updated",
        resource_type="MedicalRecordsRolloutFlag",
        resource_id=str(flag.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    return flag


@transaction.atomic
def activate_emergency_read_only(
    *,
    clinic_id: UUID,
    activating_user: AbstractBaseUser,
    reason: str,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordsRolloutFlag:
    """Activate emergency read-only mode — blocks all write operations for tenant."""
    flag = get_or_create_rollout_flag(clinic_id=clinic_id)
    flag.emergency_read_only_mode = True
    flag.emergency_activated_at = timezone.now()
    flag.emergency_activated_by = cast(Any, activating_user)
    flag.emergency_reason = reason
    flag.save(
        update_fields=[
            "emergency_read_only_mode",
            "emergency_activated_at",
            "emergency_activated_by",
            "emergency_reason",
        ]
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=activating_user.pk,
        action="medical_records_emergency.read_only_activated",
        resource_type="MedicalRecordsRolloutFlag",
        resource_id=str(flag.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    medical_records_read_only_activated.send(
        sender=MedicalRecordsRolloutFlag, flag=flag, reason=reason
    )
    return flag


@transaction.atomic
def deactivate_emergency_read_only(
    *,
    clinic_id: UUID,
    deactivating_user: AbstractBaseUser,
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordsRolloutFlag:
    """Deactivate emergency read-only mode."""
    flag = get_or_create_rollout_flag(clinic_id=clinic_id)
    flag.emergency_read_only_mode = False
    flag.save(update_fields=["emergency_read_only_mode"])
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=deactivating_user.pk,
        action="medical_records_emergency.read_only_deactivated",
        resource_type="MedicalRecordsRolloutFlag",
        resource_id=str(flag.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    medical_records_read_only_deactivated.send(
        sender=MedicalRecordsRolloutFlag, flag=flag
    )
    return flag


@transaction.atomic
def request_medical_record_export(
    *,
    clinic_id: UUID,
    requesting_user: AbstractBaseUser,
    patient_id: UUID,
    export_format: str = ExportFormat.PDF.value,
    purpose_note: str = "",
    request_id: str | None = None,
    network_origin: str = "internal",
) -> MedicalRecordExportRequest:
    """Submit a data subject access request for the full medical record (8.18.5)."""
    token = secrets.token_hex(32)
    expires_at = timezone.now() + timedelta(days=7)
    export_request = MedicalRecordExportRequest.objects.create(
        clinic_id=clinic_id,
        requested_by=cast(Any, requesting_user),
        patient_id=patient_id,
        export_format=export_format,
        status=ExportStatus.PENDING.value,
        purpose_note=purpose_note,
        download_token=token,
        token_expires_at=expires_at,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=requesting_user.pk,
        action="medical_record_export.requested",
        resource_type="MedicalRecordExportRequest",
        resource_id=str(export_request.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=network_origin,
    )
    medical_record_export_requested.send(
        sender=MedicalRecordExportRequest, export_request=export_request
    )
    return export_request
