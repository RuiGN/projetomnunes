"""Service layer for relapse prevention plans and post-lapse support (8.15.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .events import (
    post_lapse_recorded,
    relapse_plan_revoked,
    relapse_plan_shared,
    relapse_plan_updated,
)
from .models import (
    PostLapseRecord,
    RelapsePlanSection,
    RelapsePlanShare,
    RelapsePreventionPlan,
)


class RelapseService(CoreService[Any, Any]):
    """Relapse prevention domain service base."""


@transaction.atomic
def create_or_update_relapse_plan(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    title: str = "Plano de Prevenção de Recaída",
    sections_data: list[dict[str, Any]] | None = None,
    disclaimer_acknowledged: bool = True,
    actor_id: UUID | None = None,
) -> RelapsePreventionPlan:
    """Create or update versioned relapse prevention plan with structured sections."""
    plan, created = RelapsePreventionPlan.objects.for_clinic(clinic_id).get_or_create(
        patient_profile_id=patient_profile_id,
        defaults={
            "clinic_id": clinic_id,
            "title": title.strip(),
            "version": 1,
            "disclaimer_acknowledged": disclaimer_acknowledged,
            "last_reviewed_at": timezone.now(),
        },
    )

    if not created:
        plan.version += 1
        plan.title = title.strip()
        plan.disclaimer_acknowledged = disclaimer_acknowledged
        plan.last_reviewed_at = timezone.now()
        plan.save(
            update_fields=[
                "version",
                "title",
                "disclaimer_acknowledged",
                "last_reviewed_at",
                "updated_at",
            ]
        )

    if sections_data:
        for item in sections_data:
            RelapsePlanSection.objects.for_clinic(clinic_id).update_or_create(
                relapse_plan=plan,
                section_type=item["section_type"],
                defaults={
                    "clinic_id": clinic_id,
                    "title": item.get("title", item["section_type"]).strip(),
                    "content": item.get("content", "").strip(),
                    "order": item.get("order", 0),
                },
            )

    relapse_plan_updated.send(sender=RelapsePreventionPlan, plan=plan)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.relapse_plan_updated",
        resource_type="relapse_prevention_plan",
        resource_id=str(plan.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return plan


@transaction.atomic
def share_relapse_plan_section(
    *,
    clinic_id: UUID,
    plan_id: UUID,
    recipient_label: str,
    valid_until: datetime,
    section_type: str = "",
    recipient_user: AbstractBaseUser | None = None,
    actor_id: UUID | None = None,
) -> RelapsePlanShare:
    """Share specific section or entire plan with granular validity."""
    if valid_until <= timezone.now():
        raise ValidationError("Validade do compartilhamento deve ser futura.")

    plan = (
        RelapsePreventionPlan.objects.for_clinic(clinic_id).filter(pk=plan_id).first()
    )
    if not plan:
        raise ValidationError("Plano de prevenção não encontrado.")

    share = RelapsePlanShare.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        relapse_plan=plan,
        section_type=section_type.strip(),
        recipient_user=cast(Any, recipient_user),
        recipient_label=recipient_label.strip(),
        valid_until=valid_until,
        is_revoked=False,
    )

    relapse_plan_shared.send(sender=RelapsePlanShare, share=share)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.relapse_plan_shared",
        resource_type="relapse_plan_share",
        resource_id=str(share.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return share


@transaction.atomic
def revoke_relapse_plan_share(
    *,
    clinic_id: UUID,
    share_id: UUID,
    actor_id: UUID | None = None,
) -> RelapsePlanShare:
    """Revoke sharing immediately."""
    share = RelapsePlanShare.objects.for_clinic(clinic_id).filter(pk=share_id).first()
    if not share:
        raise ValidationError("Compartilhamento não encontrado.")

    share.is_revoked = True
    share.revoked_at = timezone.now()
    share.save(update_fields=["is_revoked", "revoked_at", "updated_at"])

    relapse_plan_revoked.send(sender=RelapsePlanShare, share=share)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.relapse_plan_share_revoked",
        resource_type="relapse_plan_share",
        resource_id=str(share.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return share


@transaction.atomic
def record_post_lapse_event(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    context_and_triggers: str,
    occurred_at: datetime | None = None,
    relapse_plan_id: UUID | None = None,
    protective_actions_taken: str = "",
    support_requested: bool = False,
    notes: str = "",
    actor_id: UUID | None = None,
) -> PostLapseRecord:
    """Register welcoming, non-punitive post-lapse event to reactivate coping."""
    if not context_and_triggers.strip():
        raise ValidationError("Contexto ou gatilho deve ser informado.")

    record = PostLapseRecord.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        relapse_plan_id=relapse_plan_id,
        occurred_at=occurred_at or timezone.now(),
        context_and_triggers=context_and_triggers.strip(),
        protective_actions_taken=protective_actions_taken.strip(),
        support_requested=support_requested,
        notes=notes.strip(),
    )

    post_lapse_recorded.send(sender=PostLapseRecord, record=record)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.post_lapse_event_logged",
        resource_type="post_lapse_record",
        resource_id=str(record.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return record


__all__ = [
    "RelapseService",
    "create_or_update_relapse_plan",
    "record_post_lapse_event",
    "revoke_relapse_plan_share",
    "share_relapse_plan_section",
]
