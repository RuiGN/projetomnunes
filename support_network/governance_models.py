"""Models for governance, feature flags, and rollout gates (8.16.5)."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from support_network.contracts import AgeTier
from support_network.network_models import (
    InfrastructureSupportNetworkManager,
    SupportNetworkTenantManager,
)


class SupportNetworkRolloutFlag(UUIDTimestampedModel):
    """Tenant and age-tier specific feature toggles for progressive rollout."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="support_rollout_flags",
    )
    feature_name = models.CharField(max_length=100, db_index=True)
    is_enabled = models.BooleanField(default=True)
    min_age_tier = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in AgeTier],
        default=AgeTier.CHILD.value,
    )
    cohort_name = models.CharField(max_length=50, default="GENERAL")
    rollout_percentage = models.PositiveSmallIntegerField(default=100)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_rollout_flags"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "feature_name", "cohort_name"],
                name="unique_clinic_feature_cohort",
            )
        ]


class SupportNetworkAuditMetric(UUIDTimestampedModel):
    """Pseudonymized metrics for monitoring."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="support_audit_metrics",
    )
    metric_date = models.DateField(default=timezone.localdate, db_index=True)
    invitations_sent = models.PositiveIntegerField(default=0)
    invitations_accepted = models.PositiveIntegerField(default=0)
    invitations_revoked = models.PositiveIntegerField(default=0)
    relationships_revoked = models.PositiveIntegerField(default=0)
    authorization_failures = models.PositiveIntegerField(default=0)
    average_latency_ms = models.FloatField(default=0.0)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_audit_metrics"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "metric_date"],
                name="unique_clinic_metric_date",
            )
        ]
