"""Services for optional spirituality and history purging (8.16.4)."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from support_network.contracts import (
    ContemplativeCategory,
    EditorialReviewStatus,
    SpiritualityTradition,
)
from support_network.events import (
    contemplative_history_purged,
    spirituality_preference_updated,
)
from support_network.spirituality_models import (
    ContemplativeContent,
    ContemplativeHistory,
    SpiritualityPreference,
)


@transaction.atomic
def configure_spirituality_preference(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    is_enabled: bool,
    tradition: str = SpiritualityTradition.SECULAR.value,
    secular_alternative_enabled: bool = True,
    disclaimer_acknowledged: bool = True,
    actor_id: UUID | None = None,
) -> SpiritualityPreference:
    """Configure voluntary opt-in for contemplative practices. DISABLED BY DEFAULT."""
    now = timezone.now()
    pref, _ = SpiritualityPreference.objects.for_clinic(clinic_id).update_or_create(
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
        defaults={
            "is_enabled": is_enabled,
            "tradition": tradition,
            "secular_alternative_enabled": secular_alternative_enabled,
            "opt_in_date": now if is_enabled else None,
            "disclaimer_acknowledged": disclaimer_acknowledged,
        },
    )

    if not is_enabled:
        # User opted out: automatically purge historical engagement to uphold privacy
        purge_contemplative_history(
            clinic_id=clinic_id,
            patient_profile_id=patient_profile_id,
            actor_id=actor_id,
        )

    spirituality_preference_updated.send(sender=SpiritualityPreference, preference=pref)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.spirituality_preference_updated",
        resource_type="spirituality_preference",
        resource_id=str(pref.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return pref


@transaction.atomic
def publish_contemplative_content(
    *,
    title: str,
    description: str,
    content_text: str,
    category: str = ContemplativeCategory.MINDFUL_WALK.value,
    tradition: str = SpiritualityTradition.SECULAR.value,
    duration_minutes: int = 5,
    is_secular_equivalent: bool = True,
    author_attribution: str = "",
    reviewer: AbstractBaseUser | None = None,
    clinic_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> ContemplativeContent:
    """Publish vetted contemplative content with editorial standards."""
    content = ContemplativeContent.infrastructure_objects.create(
        clinic_id=clinic_id,
        title=title.strip(),
        description=description.strip(),
        content_text=content_text.strip(),
        category=category,
        tradition=tradition,
        duration_minutes=duration_minutes,
        is_secular_equivalent=is_secular_equivalent,
        author_attribution=author_attribution.strip(),
        editorial_review_status=EditorialReviewStatus.APPROVED.value,
        reviewed_by=cast(Any, reviewer),
        reviewed_at=timezone.now() if reviewer else None,
        diversity_and_safety_cleared=True,
        non_coercive_language_verified=True,
        version=1,
        is_active=True,
    )

    if clinic_id:
        record_audit_event(
            clinic_id=clinic_id,
            actor_id=actor_id or (reviewer.pk if reviewer else None),
            action="support_network.contemplative_content_published",
            resource_type="contemplative_content",
            resource_id=str(content.id),
            outcome="success",
            request_id=uuid4(),
            network_origin=None,
        )
    return content


@transaction.atomic
def log_contemplative_session(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    content_id: UUID,
    duration_spent_seconds: int,
    completed: bool = True,
    actor_id: UUID | None = None,
) -> ContemplativeHistory:
    content = ContemplativeContent.infrastructure_objects.filter(
        id=content_id, is_active=True
    ).first()
    if not content:
        raise ValueError("Conteúdo contemplativo não encontrado.")

    history = ContemplativeHistory.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
        content=content,
        duration_spent_seconds=duration_spent_seconds,
        completed=completed,
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.contemplative_session_logged",
        resource_type="contemplative_history",
        resource_id=str(history.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return history


@transaction.atomic
def purge_contemplative_history(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    actor_id: UUID | None = None,
) -> int:
    """Purge all contemplative engagement records for patient."""
    deleted_count, _ = (
        ContemplativeHistory.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id)
        .delete()
    )

    contemplative_history_purged.send(
        sender=ContemplativeHistory,
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
        deleted_count=deleted_count,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.contemplative_history_purged",
        resource_type="contemplative_history",
        resource_id=str(patient_profile_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return deleted_count


__all__ = [
    "configure_spirituality_preference",
    "log_contemplative_session",
    "publish_contemplative_content",
    "purge_contemplative_history",
]
