"""Service layer for physical activity, check-ins, and movement plans (8.15)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .contracts import ActivityDeviceAdapter
from .events import (
    activity_device_synced,
    activity_logged,
    movement_plan_approved,
    movement_plan_feedback_received,
    movement_plan_proposed,
    overlapping_activities_resolved,
    wellness_checkin_recorded,
)
from .models import (
    ActivityDeviceSyncRecord,
    ActivityIntensity,
    ActivityLog,
    ActivityProvenance,
    MovementPlanFeedback,
    MovementPlanStatus,
    SafeMovementPlan,
    WellnessCheckIn,
)
from .policies import can_approve_movement_plan


class Service(CoreService[Any, Any]):
    """Wellness domain service base."""


@transaction.atomic
def record_activity(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    activity_type: str,
    start_time: datetime,
    duration_minutes: int,
    perceived_intensity: str = ActivityIntensity.MODERATE,
    rpe_scale: int = 4,
    distance_meters: int | None = None,
    is_accessible_assisted: bool = False,
    adaptations: str = "",
    notes: str = "",
    provenance: str = ActivityProvenance.SELF_REPORTED,
    external_record_id: str = "",
    actor_id: UUID | None = None,
) -> ActivityLog:
    """Record manual or imported physical activity with accessibility support."""
    if duration_minutes <= 0:
        raise ValidationError("Duração da atividade deve ser maior que zero.")

    if not 1 <= rpe_scale <= 10:
        raise ValidationError("Escala de esforço (RPE) deve estar entre 1 e 10.")

    log = ActivityLog.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        activity_type=activity_type.strip(),
        is_accessible_assisted=is_accessible_assisted,
        start_time=start_time,
        duration_minutes=duration_minutes,
        perceived_intensity=perceived_intensity,
        rpe_scale=rpe_scale,
        distance_meters=distance_meters,
        adaptations=adaptations.strip(),
        notes=notes.strip(),
        provenance=provenance,
        external_record_id=external_record_id.strip(),
    )

    activity_logged.send(sender=ActivityLog, log=log)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.activity_recorded",
        resource_type="activity_log",
        resource_id=str(log.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return log


@transaction.atomic
def sync_device_activities(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    device_provider: str,
    adapter: ActivityDeviceAdapter,
    actor_id: UUID | None = None,
) -> ActivityDeviceSyncRecord:
    """Import wearable telemetry incrementally with deduplication."""
    sync_rec, _ = ActivityDeviceSyncRecord.objects.for_clinic(clinic_id).get_or_create(
        patient_profile_id=patient_profile_id,
        device_provider=device_provider,
        defaults={
            "clinic_id": clinic_id,
            "last_synced_at": timezone.now(),
            "sync_cursor": "",
        },
    )

    if sync_rec.is_connection_revoked:
        raise ValidationError("Conexão com o dispositivo foi revogada.")

    data_points, next_cursor = adapter.sync_activity_records(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        sync_cursor=sync_rec.sync_cursor,
    )

    saved_count = 0
    for dp in data_points:
        exists = (
            ActivityLog.objects.for_clinic(clinic_id)
            .filter(
                patient_profile_id=patient_profile_id,
                external_record_id=dp.external_record_id,
            )
            .exists()
        )
        if not exists:
            record_activity(
                clinic_id=clinic_id,
                patient_profile_id=patient_profile_id,
                activity_type=dp.activity_type,
                start_time=dp.start_time,
                duration_minutes=dp.duration_minutes,
                distance_meters=dp.distance_meters,
                perceived_intensity=dp.perceived_intensity,
                rpe_scale=dp.rpe_scale,
                provenance=ActivityProvenance.DEVICE_IMPORTED,
                external_record_id=dp.external_record_id,
                actor_id=actor_id,
            )
            saved_count += 1

    sync_rec.sync_cursor = next_cursor
    sync_rec.last_synced_at = timezone.now()
    sync_rec.records_synced_count += saved_count
    sync_rec.save(
        update_fields=[
            "sync_cursor",
            "last_synced_at",
            "records_synced_count",
            "updated_at",
        ]
    )

    activity_device_synced.send(sender=ActivityDeviceSyncRecord, record=sync_rec)
    return sync_rec


@transaction.atomic
def resolve_overlapping_activities(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    primary_log_id: UUID,
    secondary_log_id: UUID,
    prefer_primary: bool = True,
    actor_id: UUID | None = None,
) -> tuple[ActivityLog, ActivityLog]:
    """Consolidate overlapping activities with user choice preserving original event."""
    primary = (
        ActivityLog.objects.for_clinic(clinic_id)
        .filter(pk=primary_log_id, patient_profile_id=patient_profile_id)
        .first()
    )
    secondary = (
        ActivityLog.objects.for_clinic(clinic_id)
        .filter(pk=secondary_log_id, patient_profile_id=patient_profile_id)
        .first()
    )

    if not primary or not secondary:
        raise ValidationError("Atividades sobrepostas não encontradas.")

    primary.is_overlapping_consolidated = True
    primary.is_preferred_in_trends = prefer_primary
    primary.save(
        update_fields=[
            "is_overlapping_consolidated",
            "is_preferred_in_trends",
            "updated_at",
        ]
    )

    secondary.is_overlapping_consolidated = True
    secondary.is_preferred_in_trends = not prefer_primary
    secondary.save(
        update_fields=[
            "is_overlapping_consolidated",
            "is_preferred_in_trends",
            "updated_at",
        ]
    )

    overlapping_activities_resolved.send(
        sender=ActivityLog,
        primary=primary,
        secondary=secondary,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.overlapping_activities_resolved",
        resource_type="activity_log",
        resource_id=str(primary.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return primary, secondary


@transaction.atomic
def record_wellness_checkin(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    checkin_date: date,
    energy_level: int = 3,
    perceived_mood: int = 3,
    stress_level: int = 3,
    readiness_disposition: int = 3,
    context_notes: str = "",
    is_shared_with_clinic: bool = False,
    actor_id: UUID | None = None,
) -> WellnessCheckIn:
    """Record optional daily self-report without automated diagnosis."""
    for val, name in [
        (energy_level, "Nível de energia"),
        (perceived_mood, "Humor percebido"),
        (stress_level, "Nível de estresse"),
        (readiness_disposition, "Disposição"),
    ]:
        if not 1 <= val <= 5:
            raise ValidationError(f"{name} deve estar na escala de 1 a 5.")

    checkin, created = WellnessCheckIn.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        checkin_date=checkin_date,
        defaults={
            "energy_level": energy_level,
            "perceived_mood": perceived_mood,
            "stress_level": stress_level,
            "readiness_disposition": readiness_disposition,
            "context_notes": context_notes.strip(),
            "is_shared_with_clinic": is_shared_with_clinic,
        },
    )
    if not created:
        checkin.energy_level = energy_level
        checkin.perceived_mood = perceived_mood
        checkin.stress_level = stress_level
        checkin.readiness_disposition = readiness_disposition
        checkin.context_notes = context_notes.strip()
        checkin.is_shared_with_clinic = is_shared_with_clinic
        checkin.save(
            update_fields=[
                "energy_level",
                "perceived_mood",
                "stress_level",
                "readiness_disposition",
                "context_notes",
                "is_shared_with_clinic",
                "updated_at",
            ]
        )

    wellness_checkin_recorded.send(sender=WellnessCheckIn, checkin=checkin)
    return checkin


@transaction.atomic
def propose_safe_movement_plan(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    prescribing_professional: AbstractBaseUser,
    title: str,
    objective: str,
    target_frequency: str,
    target_intensity: str,
    progression_guidelines: str,
    stop_signals: str,
    adaptations: str = "",
) -> SafeMovementPlan:
    """Propose individualized movement plan blocked until signed."""
    if not can_approve_movement_plan(
        user=prescribing_professional, clinic_id=clinic_id
    ):
        raise ValidationError(
            "Apenas profissionais habilitados podem propor planos de movimento."
        )

    plan = SafeMovementPlan.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        prescribing_professional=cast(Any, prescribing_professional),
        title=title.strip(),
        objective=objective.strip(),
        target_frequency=target_frequency.strip(),
        target_intensity=target_intensity.strip(),
        progression_guidelines=progression_guidelines.strip(),
        stop_signals=stop_signals.strip(),
        adaptations=adaptations.strip(),
        status=MovementPlanStatus.DRAFT,
    )

    movement_plan_proposed.send(sender=SafeMovementPlan, plan=plan)
    return plan


@transaction.atomic
def approve_safe_movement_plan(
    *,
    clinic_id: UUID,
    plan_id: UUID,
    signing_professional: AbstractBaseUser,
) -> SafeMovementPlan:
    """Activate movement plan with professional signature digest."""
    if not can_approve_movement_plan(user=signing_professional, clinic_id=clinic_id):
        raise ValidationError("Usuário sem autorização para assinar planos clínicos.")

    plan = SafeMovementPlan.objects.for_clinic(clinic_id).filter(pk=plan_id).first()
    if not plan:
        raise ValidationError("Plano de movimento não encontrado.")

    now = timezone.now()
    content_to_sign = (
        f"{plan.id}:{plan.title}:{plan.objective}:"
        f"{signing_professional.pk}:{now.isoformat()}"
    )
    digest = hashlib.sha256(content_to_sign.encode("utf-8")).hexdigest()

    plan.status = MovementPlanStatus.ACTIVE
    plan.signed_at = now
    plan.signature_digest = digest
    plan.save(update_fields=["status", "signed_at", "signature_digest", "updated_at"])

    movement_plan_approved.send(sender=SafeMovementPlan, plan=plan)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=signing_professional.pk,
        action="wellness.movement_plan_approved",
        resource_type="safe_movement_plan",
        resource_id=str(plan.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return plan


@transaction.atomic
def record_plan_discomfort_feedback(
    *,
    clinic_id: UUID,
    plan_id: UUID,
    patient_profile_id: UUID,
    feedback_type: str,
    description: str,
    actor_id: UUID | None = None,
) -> MovementPlanFeedback:
    """Record pain/discomfort, immediately pausing the plan for safety."""
    plan = (
        SafeMovementPlan.objects.for_clinic(clinic_id)
        .filter(pk=plan_id, patient_profile_id=patient_profile_id)
        .first()
    )
    if not plan:
        raise ValidationError("Plano de movimento não encontrado.")

    now = timezone.now()
    feedback = MovementPlanFeedback.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        movement_plan=plan,
        patient_profile_id=patient_profile_id,
        feedback_type=feedback_type.strip(),
        description=description.strip(),
        occurred_at=now,
        pause_plan_requested=True,
        requires_professional_review=True,
    )

    # Immediately pause the plan
    plan.status = MovementPlanStatus.PAUSED
    plan.save(update_fields=["status", "updated_at"])

    movement_plan_feedback_received.send(sender=MovementPlanFeedback, feedback=feedback)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.movement_plan_discomfort_paused",
        resource_type="movement_plan_feedback",
        resource_id=str(feedback.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return feedback


__all__ = [
    "Service",
    "approve_safe_movement_plan",
    "propose_safe_movement_plan",
    "record_activity",
    "record_plan_discomfort_feedback",
    "record_wellness_checkin",
    "resolve_overlapping_activities",
    "sync_device_activities",
]
