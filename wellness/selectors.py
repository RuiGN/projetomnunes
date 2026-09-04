"""Selectors for physical activity, wellness check-ins, sobriety, and crisis (8.15)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from django.utils import timezone

from core.selectors import Selector as CoreSelector

from .models import (
    MANDATORY_CRISIS_DISCLAIMER,
    ActivityLog,
    ActivityProvenance,
    CravingCheckIn,
    CrisisResourceConfig,
    GroundingExercise,
    RelapsePreventionPlan,
    SafeMovementPlan,
    SobrietyGoal,
    SupportContact,
    WellnessCheckIn,
)

SAFETY_DISCLAIMER_TEXT = (
    "Respeite seus limites individuais. Ao sentir dor, tontura, mal-estar "
    "ou desconforto, interrompa a atividade e busque orientação profissional."
)


class Selector(CoreSelector[Any, Any]):
    """Wellness domain selector."""


def activity_trends_summary(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Calculate volume, frequency, and intensity with mandatory safety notices."""
    logs = list(
        ActivityLog.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=patient_profile_id,
            start_time__date__gte=start_date,
            start_time__date__lte=end_date,
            is_preferred_in_trends=True,
        )
        .order_by("start_time")
    )

    total_sessions = len(logs)
    if total_sessions == 0:
        return {
            "total_sessions": 0,
            "total_duration_minutes": 0,
            "avg_duration_minutes": 0,
            "avg_rpe_scale": 0.0,
            "self_reported_count": 0,
            "device_imported_count": 0,
            "accessible_assisted_count": 0,
            "safety_disclaimer": SAFETY_DISCLAIMER_TEXT,
        }

    total_duration = sum(entry.duration_minutes for entry in logs)
    total_rpe = sum(entry.rpe_scale for entry in logs)
    self_reported = sum(
        1 for entry in logs if entry.provenance == ActivityProvenance.SELF_REPORTED
    )
    device_imported = sum(
        1 for entry in logs if entry.provenance == ActivityProvenance.DEVICE_IMPORTED
    )
    accessible_count = sum(1 for entry in logs if entry.is_accessible_assisted)

    return {
        "total_sessions": total_sessions,
        "total_duration_minutes": total_duration,
        "avg_duration_minutes": round(total_duration / total_sessions),
        "avg_rpe_scale": round(total_rpe / total_sessions, 1),
        "self_reported_count": self_reported,
        "device_imported_count": device_imported,
        "accessible_assisted_count": accessible_count,
        "safety_disclaimer": SAFETY_DISCLAIMER_TEXT,
    }


def wellness_checkins_summary(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    start_date: date,
    end_date: date,
    only_shared: bool = False,
) -> dict[str, Any]:
    """Provide descriptive check-in trends without automated diagnostic claims."""
    qs = ActivityLog.objects.for_clinic(clinic_id)  # noqa: F841
    checkins_qs = WellnessCheckIn.objects.for_clinic(clinic_id).filter(
        patient_profile_id=patient_profile_id,
        checkin_date__gte=start_date,
        checkin_date__lte=end_date,
    )
    if only_shared:
        checkins_qs = checkins_qs.filter(is_shared_with_clinic=True)

    checkins = list(checkins_qs.order_by("checkin_date"))
    count = len(checkins)
    if count == 0:
        return {
            "total_checkins": 0,
            "avg_energy": 0.0,
            "avg_mood": 0.0,
            "avg_stress": 0.0,
            "avg_readiness": 0.0,
            "records": [],
        }

    return {
        "total_checkins": count,
        "avg_energy": round(sum(c.energy_level for c in checkins) / count, 1),
        "avg_mood": round(sum(c.perceived_mood for c in checkins) / count, 1),
        "avg_stress": round(sum(c.stress_level for c in checkins) / count, 1),
        "avg_readiness": round(
            sum(c.readiness_disposition for c in checkins) / count, 1
        ),
        "records": [
            {
                "date": c.checkin_date.isoformat(),
                "energy": c.energy_level,
                "mood": c.perceived_mood,
                "stress": c.stress_level,
                "readiness": c.readiness_disposition,
                "is_shared": c.is_shared_with_clinic,
            }
            for c in checkins
        ],
    }


def safe_movement_plans_for_patient(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
) -> list[SafeMovementPlan]:
    """Fetch active and historic movement plans with preloaded feedbacks."""
    return list(
        SafeMovementPlan.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=patient_profile_id)
        .prefetch_related("feedbacks")
        .order_by("-created_at")
    )


def sobriety_dashboard(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
) -> dict[str, Any]:
    """Provide patient with private recovery overview without punitive streaks."""
    active_goals = list(
        SobrietyGoal.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=patient_profile_id,
            is_active=True,
        )
        .prefetch_related("milestones")
    )

    support_contacts = list(
        SupportContact.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=patient_profile_id)
        .order_by("priority_order")
    )

    recent_cravings = list(
        CravingCheckIn.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=patient_profile_id)
        .order_by("-recorded_at")[:5]
    )

    goals_data = []
    today = timezone.localdate()
    for g in active_goals:
        days_current = max(0, (today - g.reference_date).days)
        goals_data.append(
            {
                "id": str(g.id),
                "goal_type": g.goal_type,
                "substance_or_behavior": g.substance_or_behavior,
                "reference_date": g.reference_date.isoformat(),
                "days_current": None if g.hide_counter else days_current,
                "hide_counter": g.hide_counter,
                "restart_count": g.restart_count,
                "milestones_count": g.milestones.count(),
            }
        )

    return {
        "active_goals": goals_data,
        "support_contacts": [
            {
                "name": c.name,
                "relationship": c.relationship,
                "phone_number": c.phone_number,
                "priority_order": c.priority_order,
                "consent_to_reach_out": c.consent_to_reach_out,
            }
            for c in support_contacts
        ],
        "recent_cravings_count": len(recent_cravings),
    }


def relapse_plan_for_patient(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
) -> RelapsePreventionPlan | None:
    """Return active relapse prevention plan prefetching sections and shares."""
    return (
        RelapsePreventionPlan.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=patient_profile_id)
        .prefetch_related("sections", "shares")
        .first()
    )


def crisis_resources_and_grounding(
    *,
    clinic_id: UUID,
) -> dict[str, Any]:
    """Provide immediate crisis numbers and offline grounding exercises."""
    config = (
        CrisisResourceConfig.objects.for_clinic(clinic_id)
        .filter(clinic_id=clinic_id)
        .first()
    )

    grounding_exercises = list(
        GroundingExercise.objects.for_clinic(clinic_id)
        .filter(is_available_offline=True)
        .order_by("title")
    )

    return {
        "mandatory_disclaimer": (
            config.mandatory_disclaimer_text if config else MANDATORY_CRISIS_DISCLAIMER
        ),
        "emergency_medical": (config.emergency_medical_number if config else "192"),
        "emergency_fire": config.emergency_fire_number if config else "193",
        "emotional_support": (config.emotional_support_number if config else "188"),
        "custom_helpline": (
            {
                "name": config.custom_helpline_name,
                "number": config.custom_helpline_number,
            }
            if config and config.custom_helpline_name
            else None
        ),
        "grounding_exercises": [
            {
                "id": str(ex.id),
                "title": ex.title,
                "technique_type": ex.technique_type,
                "instructions": ex.instructions_markdown,
                "steps": ex.steps,
                "duration_seconds": ex.duration_seconds,
                "can_exit_anytime": ex.can_exit_anytime,
            }
            for ex in grounding_exercises
        ],
    }


__all__ = [
    "SAFETY_DISCLAIMER_TEXT",
    "Selector",
    "activity_trends_summary",
    "crisis_resources_and_grounding",
    "relapse_plan_for_patient",
    "safe_movement_plans_for_patient",
    "sobriety_dashboard",
    "wellness_checkins_summary",
]
