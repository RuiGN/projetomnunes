"""Models for optional spirituality and contemplation (8.16.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from support_network.contracts import (
    ContemplativeCategory,
    EditorialReviewStatus,
    SpiritualityTradition,
)
from support_network.network_models import (
    InfrastructureSupportNetworkManager,
    SupportNetworkTenantManager,
)


class SpiritualityPreference(UUIDTimestampedModel):
    """User-controlled spirituality toggle. DISABLED BY DEFAULT."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="spirituality_preferences",
    )
    patient = models.OneToOneField(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="spirituality_preference",
    )
    is_enabled = models.BooleanField(default=False, db_index=True)
    tradition = models.CharField(
        max_length=50,
        choices=[(t.value, t.name) for t in SpiritualityTradition],
        default=SpiritualityTradition.SECULAR.value,
    )
    secular_alternative_enabled = models.BooleanField(default=True)
    opt_in_date = models.DateTimeField(null=True, blank=True)
    disclaimer_acknowledged = models.BooleanField(default=False)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_spirituality_preferences"


class ContemplativeContent(UUIDTimestampedModel):
    """Catalog of vetted practices with editorial and neutrality approval."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="contemplative_contents",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=50,
        choices=[(c.value, c.name) for c in ContemplativeCategory],
        default=ContemplativeCategory.MINDFUL_WALK.value,
    )
    tradition = models.CharField(
        max_length=50,
        choices=[(t.value, t.name) for t in SpiritualityTradition],
        default=SpiritualityTradition.SECULAR.value,
        db_index=True,
    )
    content_text = models.TextField()
    duration_minutes = models.PositiveSmallIntegerField(default=5)
    is_secular_equivalent = models.BooleanField(default=True)
    author_attribution = models.CharField(max_length=255)
    editorial_review_status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in EditorialReviewStatus],
        default=EditorialReviewStatus.APPROVED.value,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_contemplative_contents",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    diversity_and_safety_cleared = models.BooleanField(default=True)
    non_coercive_language_verified = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_contemplative_contents"
        indexes = [
            models.Index(fields=["tradition", "is_active", "editorial_review_status"]),
        ]


class ContemplativeHistory(UUIDTimestampedModel):
    """Temporary engagement history with immediate purge capability."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="contemplative_histories",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="contemplative_histories",
    )
    content = models.ForeignKey(
        ContemplativeContent,
        on_delete=models.CASCADE,
        related_name="engagements",
    )
    accessed_at = models.DateTimeField(default=timezone.now)
    completed = models.BooleanField(default=False)
    duration_spent_seconds = models.PositiveIntegerField(default=0)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_contemplative_histories"
        indexes = [
            models.Index(fields=["clinic", "patient", "accessed_at"]),
        ]
