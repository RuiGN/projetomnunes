"""Selectors for communities, feeds, moderation tickets, and gamification."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser

from communities.community_models import (
    CommunityGroup,
    CommunityMembership,
    UserSocialBlock,
)
from communities.contracts import (
    ContentStatus,
    GroupVisibility,
    MembershipStatus,
)
from communities.gamification_models import (
    GamificationProgress,
    ResponsibleGamificationProfile,
)
from communities.governance_models import (
    CommunityRolloutFlag,
)
from communities.interaction_models import (
    CommunityComment,
    CommunityPost,
)
from communities.moderation_models import (
    EvidenceVault,
    ModerationCase,
)
from communities.policies import can_access_moderation_console
from core.selectors import Selector as CoreSelector


class Selector(CoreSelector[Any, Any]):
    """Default communities domain selector."""


def get_community_directory_for_user(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    user_age_tier: str | None = None,
) -> list[CommunityGroup]:
    """Directory of accessible groups within tenant, filtering by age-eligibility."""
    groups = list(
        CommunityGroup.objects.for_clinic(clinic_id)
        .filter(
            is_active=True,
            visibility=GroupVisibility.TENANT_DIRECTORY.value,
        )
        .order_by("name")
    )
    if not user_age_tier:
        return groups
    return [g for g in groups if g.is_eligible_for_tier(user_age_tier)]


def get_user_joined_groups(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> list[CommunityGroup]:
    """Retrieve all active community groups in which the user is an active member."""
    membership_group_ids = (
        CommunityMembership.objects.for_clinic(clinic_id)
        .filter(
            user_id=user.pk,
            status=MembershipStatus.ACTIVE.value,
        )
        .values_list("community_group_id", flat=True)
    )

    return list(
        CommunityGroup.objects.for_clinic(clinic_id)
        .filter(id__in=membership_group_ids, is_active=True)
        .order_by("-created_at")
    )


def get_group_feed_for_user(
    *,
    clinic_id: UUID,
    group_id: UUID,
    viewer_user: AbstractBaseUser,
) -> list[dict[str, Any]]:
    """Retrieve feed posts excluding authors blocked bilaterally by the viewer."""
    # Find all users blocked by viewer or who blocked viewer in this clinic
    blocked_by_viewer = set(
        UserSocialBlock.infrastructure_objects.filter(
            clinic_id=clinic_id, blocker_id=viewer_user.pk
        ).values_list("blocked_user_id", flat=True)
    )
    blocking_viewer = set(
        UserSocialBlock.infrastructure_objects.filter(
            clinic_id=clinic_id, blocked_user_id=viewer_user.pk
        ).values_list("blocker_id", flat=True)
    )
    blocked_user_ids = blocked_by_viewer | blocking_viewer

    posts_qs = (
        CommunityPost.objects.for_clinic(clinic_id)
        .filter(
            community_group_id=group_id,
            status__in=[ContentStatus.PUBLISHED.value, ContentStatus.EDITED.value],
        )
        .exclude(author_id__in=blocked_user_ids)
        .order_by("-is_pinned", "-created_at")
    )

    feed: list[dict[str, Any]] = []
    for post in posts_qs:
        # Fetch active comments excluding blocked authors
        comments_qs = (
            CommunityComment.objects.for_clinic(clinic_id)
            .filter(
                post=post,
                status__in=[ContentStatus.PUBLISHED.value, ContentStatus.EDITED.value],
            )
            .exclude(author_id__in=blocked_user_ids)
            .order_by("created_at")
        )
        feed.append(
            {
                "post": post,
                "comments": list(comments_qs),
            }
        )
    return feed


def get_moderation_queue(
    *,
    clinic_id: UUID,
    moderator_user: AbstractBaseUser,
    status: str | None = None,
) -> list[ModerationCase]:
    """Retrieve prioritized moderation cases for authorized moderators."""
    if not can_access_moderation_console(user=moderator_user, clinic_id=clinic_id):
        raise PermissionError("Access to moderation queue is forbidden.")

    qs = ModerationCase.objects.for_clinic(clinic_id)
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("-priority_score", "sla_deadline"))


def get_case_evidence(
    *,
    clinic_id: UUID,
    case_id: UUID,
    moderator_user: AbstractBaseUser,
) -> EvidenceVault:
    """Retrieve segregated evidence vault record for a specific case."""
    if not can_access_moderation_console(user=moderator_user, clinic_id=clinic_id):
        raise PermissionError("Access to evidence vault is forbidden.")

    return EvidenceVault.objects.for_clinic(clinic_id).get(case_id=case_id)


def get_gamification_summary_for_user(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> dict[str, Any] | None:
    """Retrieve private gamification status; returns None if user has not opted in."""
    profile = (
        ResponsibleGamificationProfile.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk)
        .first()
    )
    if not profile or not profile.is_opted_in:
        return None

    recent_progress = list(
        GamificationProgress.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk)
        .select_related("milestone")
        .order_by("-occurred_date")[:30]
    )

    return {
        "profile": profile,
        "is_paused": profile.is_paused,
        "reminders_enabled": profile.reminders_enabled,
        "recent_progress": recent_progress,
    }


def get_community_rollout_status(
    *,
    clinic_id: UUID,
) -> CommunityRolloutFlag:
    """Retrieve tenant rollout flag or instantiate an inactive placeholder."""
    flag = CommunityRolloutFlag.objects.for_clinic(clinic_id).first()
    if flag is None:
        flag = CommunityRolloutFlag(
            clinic_id=clinic_id,
            communities_enabled=False,
            gamification_enabled=False,
            allowed_age_tiers=[],
            moderation_kill_switch=False,
        )
    return flag
