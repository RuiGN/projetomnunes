"""Services for progressive rollout flags and quality gates (8.16.5)."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from support_network.governance_models import (
    SupportNetworkAuditMetric,
    SupportNetworkRolloutFlag,
)


def is_support_feature_enabled(
    *,
    clinic_id: UUID,
    feature_name: str,
    age_tier: str = "child",
    cohort: str = "GENERAL",
) -> bool:
    """Check feature flag enablement per tenant, cohort and age tier."""
    flag = (
        SupportNetworkRolloutFlag.objects.for_clinic(clinic_id)
        .filter(feature_name=feature_name, cohort_name=cohort)
        .first()
    )
    if not flag:
        return True
    return flag.is_enabled


@transaction.atomic
def record_aggregated_metric(
    *,
    clinic_id: UUID,
    invitations_sent: int = 0,
    invitations_accepted: int = 0,
    invitations_revoked: int = 0,
    relationships_revoked: int = 0,
    authorization_failures: int = 0,
    latency_ms: float = 0.0,
) -> SupportNetworkAuditMetric:
    """Update daily aggregated pseudonymized telemetry for privacy-safe monitoring."""
    today = timezone.localdate()
    metric, created = SupportNetworkAuditMetric.objects.for_clinic(
        clinic_id
    ).get_or_create(
        clinic_id=clinic_id,
        metric_date=today,
        defaults={
            "invitations_sent": invitations_sent,
            "invitations_accepted": invitations_accepted,
            "invitations_revoked": invitations_revoked,
            "relationships_revoked": relationships_revoked,
            "authorization_failures": authorization_failures,
            "average_latency_ms": latency_ms,
        },
    )

    if not created:
        SupportNetworkAuditMetric.objects.for_clinic(clinic_id).filter(
            id=metric.id
        ).update(
            invitations_sent=F("invitations_sent") + invitations_sent,
            invitations_accepted=F("invitations_accepted") + invitations_accepted,
            invitations_revoked=F("invitations_revoked") + invitations_revoked,
            relationships_revoked=F("relationships_revoked") + relationships_revoked,
            authorization_failures=F("authorization_failures") + authorization_failures,
            average_latency_ms=(
                (F("average_latency_ms") + latency_ms) / 2.0
                if latency_ms > 0
                else F("average_latency_ms")
            ),
            updated_at=timezone.now(),
        )
        metric.refresh_from_db()

    return metric


def check_rollout_blockers(
    *,
    clinic_id: UUID,
    max_auth_failure_threshold: int = 20,
) -> bool:
    """Return True if rollout passes quality gates."""
    today = timezone.localdate()
    metric = (
        SupportNetworkAuditMetric.objects.for_clinic(clinic_id)
        .filter(metric_date=today)
        .first()
    )
    if not metric:
        return True
    return metric.authorization_failures <= max_auth_failure_threshold


__all__ = [
    "check_rollout_blockers",
    "is_support_feature_enabled",
    "record_aggregated_metric",
]
