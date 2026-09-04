"""Services for rollout flags, emergency breakers, and operational metrics (8.17.5)."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from communities.events import (
    moderation_kill_switch_triggered,
    rollout_flag_updated,
)
from communities.governance_models import (
    CommunityAuditMetric,
    CommunityRolloutFlag,
)


@transaction.atomic
def set_community_rollout_flags(
    *,
    clinic_id: UUID,
    communities_enabled: bool,
    gamification_enabled: bool,
    allowed_age_tiers: list[str] | None = None,
    slow_mode_enforced: bool = False,
) -> CommunityRolloutFlag:
    """Configure tenant feature flags and age-tier access permissions."""
    if allowed_age_tiers is None:
        allowed_age_tiers = ["ADULT"]

    flag, _ = CommunityRolloutFlag.objects.for_clinic(clinic_id).update_or_create(
        clinic_id=clinic_id,
        defaults={
            "communities_enabled": communities_enabled,
            "gamification_enabled": gamification_enabled,
            "allowed_age_tiers": allowed_age_tiers,
            "slow_mode_enforced": slow_mode_enforced,
        },
    )

    rollout_flag_updated.send(sender=CommunityRolloutFlag, clinic_id=clinic_id)
    return flag


@transaction.atomic
def trigger_emergency_kill_switch(
    *,
    clinic_id: UUID,
    activate: bool,
    reason: str,
) -> CommunityRolloutFlag:
    """Immediately freeze posting/commenting when safety thresholds are breached."""
    flag, _ = CommunityRolloutFlag.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        defaults={
            "communities_enabled": True,
            "gamification_enabled": True,
            "allowed_age_tiers": ["ADULT"],
        },
    )
    flag.moderation_kill_switch = activate
    flag.save(update_fields=["moderation_kill_switch", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=clinic_id,
        action="communities.kill_switch_toggled",
        resource_type="community_rollout_flag",
        resource_id=str(flag.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    moderation_kill_switch_triggered.send(
        sender=CommunityRolloutFlag,
        clinic_id=clinic_id,
        active=activate,
    )
    return flag


@transaction.atomic
def record_daily_community_metric(
    *,
    clinic_id: UUID,
    metric_date: date | None = None,
    posts_delta: int = 0,
    comments_delta: int = 0,
    reports_delta: int = 0,
    moderation_actions_delta: int = 0,
    appeals_delta: int = 0,
    appeals_upheld_delta: int = 0,
    sla_minutes: float = 0.0,
    rate_limit_hits_delta: int = 0,
) -> CommunityAuditMetric:
    """Record daily pseudonymized aggregate metrics for operational telemetry."""
    if metric_date is None:
        metric_date = timezone.localdate()

    metric, _ = CommunityAuditMetric.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        metric_date=metric_date,
        defaults={
            "posts_created": 0,
            "comments_created": 0,
            "reports_submitted": 0,
            "moderation_actions_taken": 0,
            "appeals_submitted": 0,
            "appeals_upheld": 0,
            "average_sla_resolution_minutes": 0.0,
            "rate_limit_hits": 0,
        },
    )

    if posts_delta:
        metric.posts_created += posts_delta
    if comments_delta:
        metric.comments_created += comments_delta
    if reports_delta:
        metric.reports_submitted += reports_delta
    if moderation_actions_delta:
        metric.moderation_actions_taken += moderation_actions_delta
    if appeals_delta:
        metric.appeals_submitted += appeals_delta
    if appeals_upheld_delta:
        metric.appeals_upheld += appeals_upheld_delta
    if rate_limit_hits_delta:
        metric.rate_limit_hits += rate_limit_hits_delta
    if sla_minutes > 0.0:
        if metric.average_sla_resolution_minutes > 0.0:
            metric.average_sla_resolution_minutes = (
                metric.average_sla_resolution_minutes + sla_minutes
            ) / 2.0
        else:
            metric.average_sla_resolution_minutes = sla_minutes

    metric.save()
    return metric
