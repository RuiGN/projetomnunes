"""Receivers for cross-domain signals consumed by the content domain."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from django.dispatch import receiver
from django.utils import timezone

from audit.services import record_audit_event
from people.events import professional_credential_revoked

from .models import CohortMember, ContentNotification, ContentRecommendation

__all__ = ["retire_recommendations_on_credential_revocation"]


@receiver(
    professional_credential_revoked,
    dispatch_uid="content.professional_credential_revoked.v1",
)
def retire_recommendations_on_credential_revocation(
    sender: Any,
    *,
    clinic_id: UUID,
    professional_user_id: UUID,
    reason: str,
    request_id: UUID,
    **kwargs: object,
) -> None:
    """Cascade-retire active recommendations when their author is revoked.

    Connected from content.apps; keeps people free of a content import.
    """
    del sender, kwargs

    active = ContentRecommendation.infrastructure_objects.filter(
        clinic_id=clinic_id,
        recommended_by_id=professional_user_id,
        status="active",
    )
    now = timezone.now()
    for recommendation in active:
        recommendation.status = "retired"
        recommendation.retired_reason = "credential_revoked"
        recommendation.retired_at = now
        recommendation.save(
            update_fields=("status", "retired_reason", "retired_at", "updated_at")
        )
        recipient_ids: set[UUID] = set()
        if recommendation.patient_id is not None:
            recipient_ids.add(recommendation.patient_id)
        elif recommendation.cohort_id is not None:
            recipient_ids.update(
                CohortMember.infrastructure_objects.filter(
                    clinic_id=clinic_id, cohort_id=recommendation.cohort_id
                ).values_list("user_id", flat=True)
            )
        for recipient_id in sorted(recipient_ids):
            ContentNotification.infrastructure_objects.create(
                clinic_id=clinic_id,
                recipient_id=recipient_id,
                notification_kind="recommendation_retired",
                recommendation=recommendation,
                body=(
                    "Uma recomendação foi retirada (credencial profissional revogada)."
                ),
            )
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=None,
            action="update",
            resource_type="content_recommendation",
            resource_id=str(recommendation.pk),
            outcome="success",
            request_id=request_id or uuid4(),
            network_origin=None,
        )
