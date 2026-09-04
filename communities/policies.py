"""Authorization policies for communities, moderation, and gamification (8.17)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from communities.community_models import (
    CommunityGroup,
    CommunityMembership,
    UserSocialBlock,
)
from communities.contracts import GroupVisibility, MembershipRole, MembershipStatus
from communities.governance_models import CommunityRolloutFlag
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy


def _user_has_any_clinic_role(
    *, user_id: UUID, clinic_id: UUID, roles: set[str]
) -> bool:
    today = timezone.localdate()
    return any(
        has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            on_date=today,
        )
        for role in roles
    )


class AuthorizationPolicy(CoreAuthorizationPolicy[AbstractBaseUser, Any]):
    """Communities domain baseline authorization policy."""

    def is_allowed(self, subject: AbstractBaseUser, resource: Any, /) -> bool:
        if not subject.is_authenticated or not subject.is_active:
            return False
        clinic_id = getattr(resource, "clinic_id", None)
        if clinic_id is None:
            return False
        return _user_has_any_clinic_role(
            user_id=subject.pk,
            clinic_id=clinic_id,
            roles={"clinic_admin", "therapist", "patient"},
        )


def can_view_group(*, user: AbstractBaseUser, group: CommunityGroup) -> bool:
    """Determine whether a user can see a group's metadata and activity."""
    if not user.is_authenticated or not user.is_active:
        return False
    if not group.is_active:
        return False

    membership = CommunityMembership.infrastructure_objects.filter(
        community_group=group, user_id=user.pk
    ).first()

    if membership and membership.status == MembershipStatus.ACTIVE.value:
        return True

    # If not a member, visibility must allow directory browsing
    return group.visibility == GroupVisibility.TENANT_DIRECTORY.value


def can_join_group(
    *,
    user: AbstractBaseUser,
    group: CommunityGroup,
    user_age_tier: str | None = None,
) -> bool:
    """Check if a user is eligible to join a group (age tier & status)."""
    if not user.is_authenticated or not user.is_active:
        return False
    if not group.is_active:
        return False

    if user_age_tier and not group.is_eligible_for_tier(user_age_tier):
        return False

    # Check if previously suspended or banned
    membership = CommunityMembership.infrastructure_objects.filter(
        community_group=group, user_id=user.pk
    ).first()
    return not (
        membership
        and membership.status
        in {
            MembershipStatus.SUSPENDED.value,
            MembershipStatus.REMOVED.value,
        }
    )


def can_post_in_group(*, user: AbstractBaseUser, group: CommunityGroup) -> bool:
    """Check if user can post or comment in a group."""
    if not user.is_authenticated or not user.is_active:
        return False
    if not group.is_active:
        return False

    # Check kill switch
    flag = CommunityRolloutFlag.infrastructure_objects.filter(
        clinic=group.clinic
    ).first()
    if flag and flag.moderation_kill_switch:
        return False

    membership = CommunityMembership.infrastructure_objects.filter(
        community_group=group, user_id=user.pk
    ).first()
    return membership is not None and membership.status == MembershipStatus.ACTIVE.value


def can_moderate_group(*, user: AbstractBaseUser, group: CommunityGroup) -> bool:
    """Check if user has moderation authority within a group."""
    if not user.is_authenticated or not user.is_active:
        return False

    if _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=group.clinic_id,
        roles={"clinic_admin", "therapist"},
    ):
        return True

    membership = CommunityMembership.infrastructure_objects.filter(
        community_group=group, user_id=user.pk
    ).first()
    return (
        membership is not None
        and membership.status == MembershipStatus.ACTIVE.value
        and membership.role
        in {MembershipRole.OWNER.value, MembershipRole.MODERATOR.value}
    )


def can_access_moderation_console(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Check if user can view clinic-wide moderation tickets and evidence vault."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _user_has_any_clinic_role(
        user_id=user.pk,
        clinic_id=clinic_id,
        roles={"clinic_admin", "therapist"},
    )


def is_socially_blocked(*, clinic_id: UUID, user_a_id: UUID, user_b_id: UUID) -> bool:
    """Check bilateral block between two users in a clinic."""
    if user_a_id == user_b_id:
        return False
    return (
        UserSocialBlock.infrastructure_objects.filter(clinic_id=clinic_id)
        .filter(
            (models.Q(blocker_id=user_a_id, blocked_user_id=user_b_id))
            | (models.Q(blocker_id=user_b_id, blocked_user_id=user_a_id))
        )
        .exists()
    )
