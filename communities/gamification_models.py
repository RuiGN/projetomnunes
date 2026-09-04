"""Models for responsible, opt-in, non-punitive gamification (8.17.4)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from communities.community_models import (
    CommunityTenantManager,
    InfrastructureCommunityManager,
)
from communities.contracts import SelfCareCategory
from core.persistence import UUIDTimestampedModel


class ResponsibleGamificationProfile(UUIDTimestampedModel):
    """User preferences for responsible, strictly opt-in self-care milestones."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="gamification_profiles",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gamification_profile",
    )
    is_opted_in = models.BooleanField(default=False)
    is_paused = models.BooleanField(default=False)
    reminders_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    max_daily_reminders = models.PositiveIntegerField(default=3)
    opted_in_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["ResponsibleGamificationProfile"]()
    infrastructure_objects = (
        InfrastructureCommunityManager["ResponsibleGamificationProfile"]()
    )

    class Meta:
        db_table = "communities_gamification_profile"
        indexes = [
            models.Index(fields=["clinic", "user", "is_opted_in"]),
        ]

    def __str__(self) -> str:
        return f"GamificationProfile({self.user_id}, opt_in={self.is_opted_in})"


class GamificationMilestone(UUIDTimestampedModel):
    """Vetted, non-clinical catalog of self-care milestones with supportive framing."""

    category = models.CharField(
        max_length=30,
        choices=[(c.value, c.name) for c in SelfCareCategory],
        default=SelfCareCategory.REFLECTION.value,
    )
    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=150)
    description = models.TextField()
    daily_cap = models.PositiveIntegerField(default=1)
    supportive_message = models.TextField(
        default="Cada passo no seu tempo é valioso. Pausas fazem parte do caminho."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "communities_gamification_milestone"
        ordering = ["category", "title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.category})"


class GamificationProgress(UUIDTimestampedModel):
    """Private self-care achievement log with support for immediate history purge."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="gamification_progress_records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gamification_progress",
    )
    milestone = models.ForeignKey(
        GamificationMilestone,
        on_delete=models.CASCADE,
        related_name="progress_records",
    )
    occurred_date = models.DateField()
    count_today = models.PositiveIntegerField(default=1)

    objects = CommunityTenantManager["GamificationProgress"]()
    infrastructure_objects = (
        InfrastructureCommunityManager["GamificationProgress"]()
    )

    class Meta:
        db_table = "communities_gamification_progress"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "user", "milestone", "occurred_date"],
                name="unique_gamification_progress_per_day",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "user", "occurred_date"]),
        ]

