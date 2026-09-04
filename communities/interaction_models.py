"""Models for community posts, comments, empathetic reactions, and safe attachments."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from communities.community_models import (
    CommunityGroup,
    CommunityTenantManager,
    InfrastructureCommunityManager,
)
from communities.contracts import ContentStatus, ReactionType
from core.persistence import UUIDTimestampedModel


class CommunityPost(UUIDTimestampedModel):
    """Post created within a community group (8.17.2)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_posts",
    )
    community_group = models.ForeignKey(
        CommunityGroup,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_posts",
    )
    content = models.TextField()
    sanitized_content = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in ContentStatus],
        default=ContentStatus.PUBLISHED.value,
    )
    is_pinned = models.BooleanField(default=False)
    edit_count = models.PositiveIntegerField(default=0)
    last_edited_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["CommunityPost"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityPost"]()

    class Meta:
        db_table = "communities_post"
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["clinic", "community_group", "status", "-created_at"]),
            models.Index(fields=["clinic", "author", "status"]),
        ]

    def __str__(self) -> str:
        return f"Post {self.id} in {self.community_group_id} by {self.author_id}"


class CommunityComment(UUIDTimestampedModel):
    """Comment or reply within a community post thread."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_comments",
    )
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_comments",
    )
    parent_comment = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    content = models.TextField()
    sanitized_content = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in ContentStatus],
        default=ContentStatus.PUBLISHED.value,
    )

    objects = CommunityTenantManager["CommunityComment"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityComment"]()

    class Meta:
        db_table = "communities_comment"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["clinic", "post", "status", "created_at"]),
            models.Index(fields=["clinic", "author"]),
        ]


class CommunityReaction(UUIDTimestampedModel):
    """Empathetic and supportive reaction to a post or comment."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_reactions",
    )
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    comment = models.ForeignKey(
        CommunityComment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_reactions",
    )
    reaction_type = models.CharField(
        max_length=20,
        choices=[(r.value, r.name) for r in ReactionType],
        default=ReactionType.SUPPORT.value,
    )

    objects = CommunityTenantManager["CommunityReaction"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityReaction"]()

    class Meta:
        db_table = "communities_reaction"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"],
                condition=models.Q(post__isnull=False),
                name="unique_post_reaction_per_user",
            ),
            models.UniqueConstraint(
                fields=["comment", "user"],
                condition=models.Q(comment__isnull=False),
                name="unique_comment_reaction_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "post", "reaction_type"]),
            models.Index(fields=["clinic", "comment", "reaction_type"]),
        ]


class CommunityAttachment(UUIDTimestampedModel):
    """Safe media/document attachment with MIME validation and SHA256 integrity."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="community_attachments",
    )
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    sha256_hash = models.CharField(max_length=64)
    is_clean = models.BooleanField(default=True)
    scan_status = models.CharField(max_length=30, default="CLEAN")

    objects = CommunityTenantManager["CommunityAttachment"]()
    infrastructure_objects = InfrastructureCommunityManager["CommunityAttachment"]()

    class Meta:
        db_table = "communities_attachment"
        indexes = [
            models.Index(fields=["clinic", "post"]),
            models.Index(fields=["sha256_hash"]),
        ]
