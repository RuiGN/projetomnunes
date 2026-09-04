"""Service layer for sobriety journey, craving self-reports, and milestones (8.15.3)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .events import (
    craving_recorded,
    sobriety_goal_created,
    sobriety_milestone_achieved,
    support_contact_registered,
)
from .models import (
    CravingCheckIn,
    SobrietyGoal,
    SobrietyGoalType,
    SobrietyMilestone,
    SupportContact,
)


class SobrietyService(CoreService[Any, Any]):
    """Sobriety domain service base."""


@transaction.atomic
def setup_sobriety_goal(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    goal_type: str = SobrietyGoalType.ABSTINENCE,
    substance_or_behavior: str,
    reference_date: date,
    motivations: str = "",
    language_preference: str = "dia_a_dia",
    hide_counter: bool = False,
    is_private: bool = True,
    actor_id: UUID | None = None,
) -> SobrietyGoal:
    """Set up recovery goal with private-by-default and neutral phrasing."""
    if not substance_or_behavior.strip():
        raise ValidationError("Especifique o foco ou objetivo de recuperação.")

    goal = SobrietyGoal.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        goal_type=goal_type,
        substance_or_behavior=substance_or_behavior.strip(),
        reference_date=reference_date,
        initial_start_date=reference_date,
        restart_count=0,
        motivations=motivations.strip(),
        language_preference=language_preference,
        hide_counter=hide_counter,
        is_private=is_private,
        is_active=True,
    )

    sobriety_goal_created.send(sender=SobrietyGoal, goal=goal)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.sobriety_goal_created",
        resource_type="sobriety_goal",
        resource_id=str(goal.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return goal


@transaction.atomic
def adjust_or_restart_sobriety_goal(
    *,
    clinic_id: UUID,
    goal_id: UUID,
    new_reference_date: date,
    new_motivations: str = "",
    hide_counter: bool | None = None,
    actor_id: UUID | None = None,
) -> SobrietyGoal:
    """Ajuste ou recomeço não punitivo, mantendo histórico intacto."""
    goal = SobrietyGoal.objects.for_clinic(clinic_id).filter(pk=goal_id).first()
    if not goal:
        raise ValidationError("Objetivo de sobriedade não encontrado.")

    goal.reference_date = new_reference_date
    goal.restart_count += 1
    if new_motivations:
        goal.motivations = new_motivations.strip()
    if hide_counter is not None:
        goal.hide_counter = hide_counter

    goal.save(
        update_fields=[
            "reference_date",
            "restart_count",
            "motivations",
            "hide_counter",
            "updated_at",
        ]
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="wellness.sobriety_goal_adjusted",
        resource_type="sobriety_goal",
        resource_id=str(goal.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return goal


@transaction.atomic
def record_craving_checkin(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    sobriety_goal_id: UUID | None = None,
    intensity: int | None = None,
    triggers_context: str = "",
    coping_strategy_used: str = "",
    perceived_outcome: str = "",
    protected_from_lockscreen: bool = True,
    actor_id: UUID | None = None,
) -> CravingCheckIn:
    """Log optional craving self-report with lock screen privacy."""
    if intensity is not None and not 1 <= intensity <= 10:
        raise ValidationError("Intensidade da fissura deve estar entre 1 e 10.")

    now = timezone.now()
    checkin = CravingCheckIn.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        sobriety_goal_id=sobriety_goal_id,
        intensity=intensity,
        triggers_context=triggers_context.strip(),
        coping_strategy_used=coping_strategy_used.strip(),
        perceived_outcome=perceived_outcome.strip(),
        recorded_at=now,
        protected_from_lockscreen=protected_from_lockscreen,
    )

    craving_recorded.send(sender=CravingCheckIn, checkin=checkin)
    return checkin


@transaction.atomic
def record_sobriety_milestone(
    *,
    clinic_id: UUID,
    sobriety_goal_id: UUID,
    days_count: int,
    recognition_title: str,
    achieved_at: date | None = None,
    is_private: bool = True,
) -> SobrietyMilestone:
    """Record private milestone celebration without rankings or public pressure."""
    if days_count <= 0:
        raise ValidationError("Contagem de dias deve ser positiva.")

    goal = (
        SobrietyGoal.objects.for_clinic(clinic_id).filter(pk=sobriety_goal_id).first()
    )
    if not goal:
        raise ValidationError("Objetivo de sobriedade não encontrado.")

    milestone = SobrietyMilestone.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        sobriety_goal=goal,
        days_count=days_count,
        recognition_title=recognition_title.strip(),
        achieved_at=achieved_at or timezone.localdate(),
        is_private=is_private,
    )

    sobriety_milestone_achieved.send(sender=SobrietyMilestone, milestone=milestone)
    return milestone


@transaction.atomic
def register_support_contact(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    name: str,
    relationship: str,
    phone_number: str,
    priority_order: int = 1,
    consent_to_reach_out: bool = True,
    availability_notes: str = "",
) -> SupportContact:
    """Register support contact with explicit consent to reach out."""
    contact = SupportContact.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        name=name.strip(),
        relationship=relationship.strip(),
        phone_number=phone_number.strip(),
        priority_order=priority_order,
        consent_to_reach_out=consent_to_reach_out,
        availability_notes=availability_notes.strip(),
    )

    support_contact_registered.send(sender=SupportContact, contact=contact)
    return contact


__all__ = [
    "SobrietyService",
    "adjust_or_restart_sobriety_goal",
    "record_craving_checkin",
    "record_sobriety_milestone",
    "register_support_contact",
    "setup_sobriety_goal",
]
