"""Service layer for safe, non-prescriptive medication tracking (8.14.3)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .events import medication_dose_logged, medication_registered
from .models import (
    MedicationAdministrationRoute,
    MedicationConsentShare,
    MedicationLog,
    MedicationLogStatus,
    PrescribedMedication,
)

FORBIDDEN_PRESCRIPTIVE_PATTERNS = [
    "tome o dobro",
    "compensar a dose",
    "duplique a dose",
    "aumente a dose",
    "diminua a dose",
    "troque de medicamento",
    "substitua o medicamento",
    "interrompa o tratamento",
    "inicie por conta própria",
]


class Service(CoreService[Any, Any]):
    """Medication domain service base."""


def validate_non_prescriptive_content(text: str) -> None:
    """Validate that instructions do not contain automated prescriptive advice."""
    lower = text.lower()
    for pattern in FORBIDDEN_PRESCRIPTIVE_PATTERNS:
        if pattern in lower:
            raise ValidationError(
                f"Conteúdo vedado por segurança clínica: a plataforma não "
                f"permite orientações que sugiram alteração ou compensação de dose "
                f"('{pattern}')."
            )


@transaction.atomic
def register_prescribed_medication(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    medication_name: str,
    presentation: str,
    prescribed_dose: str,
    route: str = MedicationAdministrationRoute.ORAL,
    schedule_times: list[str],
    start_date: date,
    end_date: date | None = None,
    is_continuous: bool = False,
    prescriber_name: str,
    prescriber_registration: str,
    prescription_date: date,
    instructions: str = "",
    reminder_enabled: bool = True,
    quiet_hours_start: time | None = None,
    quiet_hours_end: time | None = None,
) -> PrescribedMedication:
    """Register an existing external prescription strictly for adherence reminders."""
    clean_name = medication_name.strip()
    clean_prescriber = prescriber_name.strip()
    clean_reg = prescriber_registration.strip()

    if not clean_name:
        raise ValidationError("Nome do medicamento é obrigatório.")
    if not clean_prescriber or not clean_reg:
        raise ValidationError(
            "Identificação do prescritor externo (nome e CRM/CRO) é obrigatória."
        )

    if instructions:
        validate_non_prescriptive_content(instructions)

    med = PrescribedMedication.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        medication_name=clean_name,
        presentation=presentation.strip(),
        prescribed_dose=prescribed_dose.strip(),
        route=route,
        schedule_times=list(schedule_times),
        start_date=start_date,
        end_date=end_date,
        is_continuous=is_continuous,
        is_active=True,
        prescriber_name=clean_prescriber,
        prescriber_registration=clean_reg,
        prescription_date=prescription_date,
        instructions=instructions.strip(),
        reminder_enabled=reminder_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )
    medication_registered.send(sender=PrescribedMedication, medication=med)
    return med


@transaction.atomic
def record_medication_dose(
    *,
    clinic_id: UUID,
    medication_id: UUID,
    scheduled_time: datetime,
    status: str = MedicationLogStatus.TAKEN,
    actual_time: datetime | None = None,
    notes: str = "",
) -> MedicationLog:
    """Record execution of a dose without automated dose compensation."""
    med = (
        PrescribedMedication.objects.for_clinic(clinic_id)
        .filter(pk=medication_id)
        .first()
    )
    if not med:
        raise ValidationError("Medicamento não encontrado.")

    if notes:
        validate_non_prescriptive_content(notes)

    now = timezone.now()
    eff_time = actual_time or (now if status == MedicationLogStatus.TAKEN else None)
    log, created = MedicationLog.objects.for_clinic(clinic_id).get_or_create(
        medication=med,
        scheduled_time=scheduled_time,
        defaults={
            "clinic_id": clinic_id,
            "status": status,
            "actual_time": eff_time,
            "notes": notes.strip(),
            "recorded_at": now,
        },
    )
    if not created:
        log.status = status
        log.actual_time = eff_time
        log.notes = notes.strip()
        log.recorded_at = now
        log.save(
            update_fields=[
                "status",
                "actual_time",
                "notes",
                "recorded_at",
                "updated_at",
            ]
        )

    medication_dose_logged.send(sender=MedicationLog, log=log)
    return log


@transaction.atomic
def grant_medication_share_consent(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    granted_to_user_id: UUID,
    actor_id: UUID,
) -> MedicationConsentShare:
    """Grant clinician read access to medication adherence records with audit."""
    share, created = MedicationConsentShare.objects.for_clinic(clinic_id).get_or_create(
        patient_profile_id=patient_profile_id,
        granted_to_user_id=granted_to_user_id,
        defaults={
            "clinic_id": clinic_id,
            "is_active": True,
            "revoked_at": None,
        },
    )
    if not created and not share.is_active:
        share.is_active = True
        share.revoked_at = None
        share.save(update_fields=["is_active", "revoked_at", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="routines.medication_consent_granted",
        resource_type="medication_consent",
        resource_id=str(share.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification="Patient granted clinician medication adherence visibility",
    )
    return share


@transaction.atomic
def revoke_medication_share_consent(
    *,
    clinic_id: UUID,
    consent_id: UUID,
    actor_id: UUID,
) -> None:
    """Immediately revoke clinician access to medication adherence records."""
    share = (
        MedicationConsentShare.objects.for_clinic(clinic_id)
        .filter(pk=consent_id)
        .first()
    )
    if not share:
        raise ValidationError("Consentimento de compartilhamento não encontrado.")

    share.is_active = False
    share.revoked_at = timezone.now()
    share.save(update_fields=["is_active", "revoked_at", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="routines.medication_consent_revoked",
        resource_type="medication_consent",
        resource_id=str(share.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification="Patient revoked clinician medication adherence visibility",
    )


__all__ = [
    "Service",
    "grant_medication_share_consent",
    "record_medication_dose",
    "register_prescribed_medication",
    "revoke_medication_share_consent",
    "validate_non_prescriptive_content",
]
