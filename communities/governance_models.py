"""Models for community rollout flags, kill-switches, and aggregate metrics (8.17.5)."""

from __future__ import annotations

from django.db import models

from communities.community_models import (
    CommunityTenantManager,
    InfrastructureCommunityManager,
)
from core.persistence import UUIDTimestampedModel


class CommunityRolloutFlag(UUIDTimestampedModel):
    """Tenant-level rollout controls and safety breakers for communities."""

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_rollout_flag",
    )
    communities_enabled = models.BooleanField(default=False)
    gamification_enabled = models.BooleanField(default=False)
    allowed_age_tiers = models.JSONField(default=list)
    moderation_kill_switch = models.BooleanField(default=False)
    slow_mode_enforced = models.BooleanField(default=False)

    objects = CommunityTenantManager["CommunityRolloutFlag"]()
    infrastructure_objects = (
        InfrastructureCommunityManager["CommunityRolloutFlag"]()
    )

    class Meta:
        db_table = "communities_rollout_flag"

    def __str__(self) -> str:
        return f"RolloutFlag(clinic={self.clinic_id})"


class CommunityAuditMetric(UUIDTimestampedModel):
    """Pseudonymized aggregate telemetry for community and moderation health."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_metrics",
    )
    metric_date = models.DateField()
    posts_created = models.PositiveIntegerField(default=0)
    comments_created = models.PositiveIntegerField(default=0)
    reports_submitted = models.PositiveIntegerField(default=0)
    moderation_actions_taken = models.PositiveIntegerField(default=0)
    appeals_submitted = models.PositiveIntegerField(default=0)
    appeals_upheld = models.PositiveIntegerField(default=0)
    average_sla_resolution_minutes = models.FloatField(default=0.0)
    rate_limit_hits = models.PositiveIntegerField(default=0)

    objects = CommunityTenantManager["CommunityAuditMetric"]()
    infrastructure_objects = (
        InfrastructureCommunityManager["CommunityAuditMetric"]()
    )

    class Meta:
        db_table = "communities_audit_metric"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "metric_date"],
                name="unique_community_metric_per_clinic_day",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "metric_date"]),
        ]

