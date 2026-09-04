"""Models for community groups, memberships, invitations, and social blocking."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from django.conf import settings
from django.db import models
from django.utils import timezone

from communities.contracts import (
    GroupType,
    GroupVisibility,
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
)
from core.persistence import UUIDTimestampedModel

_ModelT = TypeVar("_ModelT", bound=models.Model)


class CommunityQuerySet(models.QuerySet[_ModelT]):
    """Tenant-scoped query set for community domain models."""

    def for_clinic(
        self: CommunityQuerySet[_ModelT], clinic_id: UUID
    ) -> CommunityQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class CommunityTenantManager(models.Manager[_ModelT]):
    """Tenant-safe default manager requiring an explicit clinic scope."""

    def get_queryset(self) -> CommunityQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return CommunityQuerySet(self.model, using=self._db)
        raise RuntimeError("Community queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: CommunityTenantManager[_ModelT], clinic_id: UUID
    ) -> CommunityQuerySet[_ModelT]:
        return CommunityQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureCommunityManager(models.Manager[_ModelT]):
    """Unrestricted community access for internal maintenance and tests."""

    def get_queryset(
        self: InfrastructureCommunityManager[_ModelT],
    ) -> CommunityQuerySet[_ModelT]:
        return CommunityQuerySet(self.model, using=self._db)


class CommunityGroup(UUIDTimestampedModel):
    """Community group or themed peer space within a clinic tenant (8.17.1)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_groups",
    )
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160)
    description = models.TextField(blank=True, default="")
    group_type = models.CharField(
        max_length=30,
        choices=[(t.value, t.name) for t in GroupType],
        default=GroupType.THEMATIC_APPROVED.value,
    )
    visibility = models.CharField(
        max_length=30,
        choices=[(v.value, v.name) for v in GroupVisibility],
        default=GroupVisibility.TENANT_DIRECTORY.value,
    )
    rules_text = models.TextField(
        default="Espaço de convivência respeitosa, sigilo mútuo e acolhimento."
    )
    rules_version = models.PositiveIntegerField(default=1)
    allowed_age_tiers = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_community_groups",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_community_groups",
    )
    slow_mode_seconds = models.PositiveIntegerField(default=0)

    objects = CommunityTenantManager["CommunityGroup"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityGroup"]()

    class Meta:
        db_table = "communities_group"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "slug"],
                name="unique_community_group_slug_per_clinic",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "is_active", "visibility"]),
            models.Index(fields=["clinic", "group_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.clinic_id})"

    def is_eligible_for_tier(self, age_tier: str) -> bool:
        if not self.allowed_age_tiers:
            return True
        return age_tier in self.allowed_age_tiers


class CommunityMembership(UUIDTimestampedModel):
    """Membership of an authenticated user inside a community group."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_memberships",
    )
    community_group = models.ForeignKey(
        CommunityGroup,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=[(r.value, r.name) for r in MembershipRole],
        default=MembershipRole.MEMBER.value,
    )
    pseudonym = models.CharField(max_length=80, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in MembershipStatus],
        default=MembershipStatus.ACTIVE.value,
    )
    rules_accepted_version = models.PositiveIntegerField(default=1)
    rules_accepted_at = models.DateTimeField(default=timezone.now)
    notification_enabled = models.BooleanField(default=True)
    muted_until = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["CommunityMembership"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityMembership"]()

    class Meta:
        db_table = "communities_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["community_group", "user"],
                name="unique_community_membership_per_group",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "user", "status"]),
            models.Index(fields=["community_group", "status", "role"]),
        ]

    def __str__(self) -> str:
        return f"Member {self.user_id} in {self.community_group_id} ({self.role})"

    @property
    def display_name(self) -> str:
        if self.pseudonym:
            return self.pseudonym
        return f"Participante-{str(self.id)[:8]}"


class CommunityInvitation(UUIDTimestampedModel):
    """Secure invitation to join a private or thematic community group."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_invitations",
    )
    community_group = models.ForeignKey(
        CommunityGroup,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_community_invitations",
    )
    invitee_email = models.EmailField()
    invitee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_community_invitations",
    )
    role_offered = models.CharField(
        max_length=20,
        choices=[(r.value, r.name) for r in MembershipRole],
        default=MembershipRole.MEMBER.value,
    )
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in InvitationStatus],
        default=InvitationStatus.PENDING.value,
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["CommunityInvitation"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityInvitation"]()

    class Meta:
        db_table = "communities_invitation"
        indexes = [
            models.Index(fields=["clinic", "invitee_email", "status"]),
            models.Index(fields=["token_hash", "status"]),
        ]

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


class UserSocialBlock(UUIDTimestampedModel):
    """Bilateral social blocking between users within a clinic tenant (8.17.2)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="social_blocks",
    )
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_blocked_users",
    )
    blocked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_blocked_by",
    )

    objects = CommunityTenantManager["UserSocialBlock"]()
    infrastructure_objects = InfrastructureCommunityManager["UserSocialBlock"]()

    class Meta:
        db_table = "communities_user_block"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "blocker", "blocked_user"],
                name="unique_social_block_per_pair",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "blocker"]),
            models.Index(fields=["clinic", "blocked_user"]),
        ]


class UserSocialMute(UUIDTimestampedModel):
    """Silencing of another user's contributions in feeds and notifications."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="social_mutes",
    )
    muter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_muted_users",
    )
    muted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_muted_by",
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["UserSocialMute"]()
    infrastructure_objects = InfrastructureCommunityManager["UserSocialMute"]()

    class Meta:
        db_table = "communities_user_mute"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "muter", "muted_user"],
                name="unique_social_mute_per_pair",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "muter"]),
        ]

