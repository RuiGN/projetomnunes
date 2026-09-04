"""Services for publishing posts, comments, reactions, and social safety (8.17.2)."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from communities.community_models import (
    CommunityGroup,
    UserSocialBlock,
    UserSocialMute,
)
from communities.contracts import (
    ALLOWED_ATTACHMENT_MIME_TYPES,
    MAX_ATTACHMENT_SIZE_BYTES,
    ContentStatus,
    ReactionType,
)
from communities.events import (
    comment_published,
    post_deleted,
    post_edited,
    post_published,
    reaction_added,
    user_blocked,
    user_muted,
)
from communities.interaction_models import (
    CommunityAttachment,
    CommunityComment,
    CommunityPost,
    CommunityReaction,
)
from communities.policies import (
    can_moderate_group,
    can_post_in_group,
    is_socially_blocked,
)

_SCRIPT_TAG_RE = re.compile(
    r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_community_text(text: str) -> str:
    """Sanitize user text input to neutralize XSS and strip raw scripting tags."""
    if not text:
        return ""
    # Strip script elements completely
    cleaned = _SCRIPT_TAG_RE.sub("", text)
    # Strip remaining dangerous HTML tags
    cleaned = _TAG_RE.sub("", cleaned)
    # Escape entities for safe rendering
    return html.escape(cleaned).strip()


@transaction.atomic
def publish_post(
    *,
    clinic_id: UUID,
    group_id: UUID,
    author_user: AbstractBaseUser,
    content: str,
) -> CommunityPost:
    """Publish a post inside a community group after rate-limit and sanity checks."""
    group = CommunityGroup.objects.for_clinic(clinic_id).get(id=group_id)
    if not can_post_in_group(user=author_user, group=group):
        raise PermissionError("User is not authorized to post in this group.")

    # Slow mode verification
    if group.slow_mode_seconds > 0:
        recent_cutoff = timezone.now() - timedelta(seconds=group.slow_mode_seconds)
        has_recent = (
            CommunityPost.objects.for_clinic(clinic_id)
            .filter(
                community_group=group,
                author_id=author_user.pk,
                created_at__gte=recent_cutoff,
            )
            .exists()
        )
        if has_recent:
            raise ValueError(
                f"Slow mode active: wait {group.slow_mode_seconds}s between posts."
            )

    sanitized = sanitize_community_text(content)
    if not sanitized:
        raise ValueError("Post content cannot be empty or only whitespace.")

    post = CommunityPost.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        community_group=group,
        author=cast(Any, author_user),
        content=content,
        sanitized_content=sanitized,
        status=ContentStatus.PUBLISHED.value,
    )

    post_published.send(sender=CommunityPost, post_id=post.id, group_id=group.id)
    return post


@transaction.atomic
def edit_post(
    *,
    clinic_id: UUID,
    post_id: UUID,
    author_user: AbstractBaseUser,
    new_content: str,
) -> CommunityPost:
    """Edit an existing post."""
    post = CommunityPost.objects.for_clinic(clinic_id).get(id=post_id)
    if post.author_id != author_user.pk:
        raise PermissionError("Only the author can edit this post.")
    if post.status in {
        ContentStatus.DELETED.value,
        ContentStatus.HIDDEN_BY_MODERATOR.value,
    }:
        raise ValueError("Cannot edit a deleted or hidden post.")

    sanitized = sanitize_community_text(new_content)
    if not sanitized:
        raise ValueError("Content cannot be empty.")

    post.content = new_content
    post.sanitized_content = sanitized
    post.status = ContentStatus.EDITED.value
    post.edit_count += 1
    post.last_edited_at = timezone.now()
    post.save(
        update_fields=[
            "content",
            "sanitized_content",
            "status",
            "edit_count",
            "last_edited_at",
            "updated_at",
        ]
    )

    post_edited.send(sender=CommunityPost, post_id=post.id)
    return post


@transaction.atomic
def delete_post(
    *,
    clinic_id: UUID,
    post_id: UUID,
    user: AbstractBaseUser,
) -> CommunityPost:
    """Logical deletion of a post by author or group moderator."""
    post = CommunityPost.objects.for_clinic(clinic_id).get(id=post_id)
    is_author = post.author_id == user.pk
    is_mod = can_moderate_group(user=user, group=post.community_group)

    if not (is_author or is_mod):
        raise PermissionError("Not authorized to delete this post.")

    post.status = ContentStatus.DELETED.value
    post.save(update_fields=["status", "updated_at"])

    post_deleted.send(sender=CommunityPost, post_id=post.id)
    return post


@transaction.atomic
def add_comment(
    *,
    clinic_id: UUID,
    post_id: UUID,
    author_user: AbstractBaseUser,
    content: str,
    parent_comment_id: UUID | None = None,
) -> CommunityComment:
    """Publish a comment or reply to a post."""
    post = CommunityPost.objects.for_clinic(clinic_id).get(id=post_id)
    if not can_post_in_group(user=author_user, group=post.community_group):
        raise PermissionError("User is not authorized to comment in this group.")

    # Bilateral block check between commenter and post author
    if is_socially_blocked(
        clinic_id=clinic_id,
        user_a_id=author_user.pk,
        user_b_id=post.author_id,
    ):
        raise PermissionError("Cannot comment due to social block.")

    sanitized = sanitize_community_text(content)
    if not sanitized:
        raise ValueError("Comment content cannot be empty.")

    parent = None
    if parent_comment_id:
        parent = CommunityComment.objects.for_clinic(clinic_id).get(
            id=parent_comment_id
        )

    comment = CommunityComment.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        post=post,
        author=cast(Any, author_user),
        parent_comment=parent,
        content=content,
        sanitized_content=sanitized,
        status=ContentStatus.PUBLISHED.value,
    )

    comment_published.send(
        sender=CommunityComment, comment_id=comment.id, post_id=post.id
    )
    return comment


@transaction.atomic
def add_reaction(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    reaction_type: str,
    post_id: UUID | None = None,
    comment_id: UUID | None = None,
) -> CommunityReaction:
    """Add or update an empathetic reaction on a post or comment."""
    if (post_id is None and comment_id is None) or (post_id and comment_id):
        raise ValueError("Reaction must target either a post or a comment.")

    valid_types = {t.value for t in ReactionType}
    if reaction_type not in valid_types:
        raise ValueError(f"Invalid reaction type: {reaction_type}")

    if post_id:
        post = CommunityPost.objects.for_clinic(clinic_id).get(id=post_id)
        if is_socially_blocked(
            clinic_id=clinic_id, user_a_id=user.pk, user_b_id=post.author_id
        ):
            raise PermissionError("Cannot react due to social block.")

        reaction, _ = CommunityReaction.objects.for_clinic(clinic_id).update_or_create(
            post=post,
            user=cast(Any, user),
            defaults={"clinic_id": clinic_id, "reaction_type": reaction_type},
        )
    else:
        assert comment_id is not None
        comment = CommunityComment.objects.for_clinic(clinic_id).get(id=comment_id)
        if is_socially_blocked(
            clinic_id=clinic_id, user_a_id=user.pk, user_b_id=comment.author_id
        ):
            raise PermissionError("Cannot react due to social block.")

        reaction, _ = CommunityReaction.objects.for_clinic(clinic_id).update_or_create(
            comment=comment,
            user=cast(Any, user),
            defaults={"clinic_id": clinic_id, "reaction_type": reaction_type},
        )

    reaction_added.send(sender=CommunityReaction, reaction_id=reaction.id)
    return reaction


@transaction.atomic
def block_user_bilaterally(
    *,
    clinic_id: UUID,
    blocker_user: AbstractBaseUser,
    blocked_user_id: UUID,
) -> UserSocialBlock:
    """Establish a bilateral social block (both parties hidden from each other)."""
    if blocker_user.pk == blocked_user_id:
        raise ValueError("Cannot block oneself.")

    block, _ = UserSocialBlock.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        blocker=cast(Any, blocker_user),
        blocked_user_id=blocked_user_id,
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=blocker_user.pk,
        action="communities.user_blocked",
        resource_type="user_social_block",
        resource_id=str(block.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    user_blocked.send(
        sender=UserSocialBlock,
        blocker_id=blocker_user.pk,
        blocked_id=blocked_user_id,
    )
    return block


@transaction.atomic
def unblock_user(
    *,
    clinic_id: UUID,
    blocker_user: AbstractBaseUser,
    blocked_user_id: UUID,
) -> None:
    """Remove a previously established social block."""
    UserSocialBlock.objects.for_clinic(clinic_id).filter(
        blocker_id=blocker_user.pk,
        blocked_user_id=blocked_user_id,
    ).delete()


@transaction.atomic
def mute_user_socially(
    *,
    clinic_id: UUID,
    muter_user: AbstractBaseUser,
    muted_user_id: UUID,
    duration_days: int | None = None,
) -> UserSocialMute:
    """Mute a user's contributions in feeds and notifications."""
    if muter_user.pk == muted_user_id:
        raise ValueError("Cannot mute oneself.")

    expires_at = (
        timezone.now() + timedelta(days=duration_days) if duration_days else None
    )

    mute, _ = UserSocialMute.objects.for_clinic(clinic_id).update_or_create(
        clinic_id=clinic_id,
        muter=cast(Any, muter_user),
        muted_user_id=muted_user_id,
        defaults={"expires_at": expires_at},
    )

    user_muted.send(
        sender=UserSocialMute, muter_id=muter_user.pk, muted_id=muted_user_id
    )
    return mute


@transaction.atomic
def attach_file_to_post(
    *,
    clinic_id: UUID,
    post_id: UUID,
    uploader_user: AbstractBaseUser,
    file_name: str,
    mime_type: str,
    file_bytes: bytes,
) -> CommunityAttachment:
    """Verify MIME, check byte size, compute SHA256, and attach file to post."""
    post = CommunityPost.objects.for_clinic(clinic_id).get(id=post_id)
    if post.author_id != uploader_user.pk:
        raise PermissionError("Only post author can add attachments.")

    if mime_type not in ALLOWED_ATTACHMENT_MIME_TYPES:
        allowed = list(ALLOWED_ATTACHMENT_MIME_TYPES)
        raise ValueError(f"MIME type '{mime_type}' not allowed. Allowed: {allowed}")

    size = len(file_bytes)
    if size > MAX_ATTACHMENT_SIZE_BYTES:
        raise ValueError(f"File size exceeds {MAX_ATTACHMENT_SIZE_BYTES} bytes.")

    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    attachment = CommunityAttachment.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        post=post,
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=size,
        sha256_hash=sha256_hash,
        is_clean=True,
        scan_status="CLEAN",
    )
    return attachment
