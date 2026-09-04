"""Services for community groups, memberships, and invitations (8.17.1)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from communities.community_models import (
    CommunityGroup,
    CommunityInvitation,
    CommunityMembership,
)
from communities.contracts import (
    GroupType,
    GroupVisibility,
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
)
from communities.events import (
    community_group_closed,
    community_group_created,
    membership_joined,
    membership_left,
)
from communities.policies import can_join_group, can_moderate_group
from core.services import Service as CoreService


class Service(CoreService[Any, Any]):
    """Communities domain service base."""


@transaction.atomic
def create_community_group(
    *,
    clinic_id: UUID,
    creator_user: AbstractBaseUser,
    name: str,
    slug: str,
    description: str = "",
    group_type: str = GroupType.THEMATIC_APPROVED.value,
    visibility: str = GroupVisibility.TENANT_DIRECTORY.value,
    rules_text: str = "Respeito mútuo, acolhimento e escuta empática.",
    rules_version: int = 1,
    allowed_age_tiers: list[str] | None = None,
    slow_mode_seconds: int = 0,
) -> CommunityGroup:
    """Create a new community group and register the creator as OWNER."""
    if allowed_age_tiers is None:
        allowed_age_tiers = ["ADULT"]

    group = CommunityGroup.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        name=name,
        slug=slug,
        description=description,
        group_type=group_type,
        visibility=visibility,
        rules_text=rules_text,
        rules_version=rules_version,
        allowed_age_tiers=allowed_age_tiers,
        slow_mode_seconds=slow_mode_seconds,
        created_by=cast(Any, creator_user),
        is_active=True,
    )

    # Register creator as OWNER
    CommunityMembership.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        community_group=group,
        user=cast(Any, creator_user),
        role=MembershipRole.OWNER.value,
        status=MembershipStatus.ACTIVE.value,
        rules_accepted_version=rules_version,
        rules_accepted_at=timezone.now(),
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=creator_user.pk,
        action="communities.group_created",
        resource_type="community_group",
        resource_id=str(group.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    community_group_created.send(sender=CommunityGroup, group_id=group.id)
    return group


@transaction.atomic
def invite_user_to_group(
    *,
    clinic_id: UUID,
    inviter_user: AbstractBaseUser,
    group_id: UUID,
    invitee_email: str,
    role_offered: str = MembershipRole.MEMBER.value,
    expires_in_days: int = 7,
) -> CommunityInvitation:
    """Issue a secure, tokenized invitation to join a group."""
    group = CommunityGroup.objects.for_clinic(clinic_id).get(id=group_id)
    if not can_moderate_group(user=inviter_user, group=group):
        raise PermissionError("Only group owners and moderators can issue invitations.")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = timezone.now() + timedelta(days=expires_in_days)

    invitation = CommunityInvitation.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        community_group=group,
        inviter=cast(Any, inviter_user),
        invitee_email=invitee_email,
        role_offered=role_offered,
        token_hash=token_hash,
        expires_at=expires_at,
        status=InvitationStatus.PENDING.value,
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=inviter_user.pk,
        action="communities.invitation_created",
        resource_type="community_invitation",
        resource_id=str(invitation.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return invitation


@transaction.atomic
def respond_to_group_invitation(
    *,
    clinic_id: UUID,
    invitation_id: UUID,
    user: AbstractBaseUser,
    accept: bool,
    pseudonym: str | None = None,
) -> CommunityMembership | None:
    """Accept or decline a community group invitation."""
    invitation = CommunityInvitation.objects.for_clinic(clinic_id).get(id=invitation_id)
    if invitation.status != InvitationStatus.PENDING.value:
        raise ValueError("Invitation is no longer pending.")
    if invitation.is_expired():
        invitation.status = InvitationStatus.EXPIRED.value
        invitation.save(update_fields=["status", "updated_at"])
        raise ValueError("Invitation has expired.")

    invitation.invitee_user = cast(Any, user)
    invitation.responded_at = timezone.now()

    if not accept:
        invitation.status = InvitationStatus.DECLINED.value
        invitation.save(
            update_fields=["status", "invitee_user", "responded_at", "updated_at"]
        )
        return None

    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.save(
        update_fields=["status", "invitee_user", "responded_at", "updated_at"]
    )

    membership, _ = CommunityMembership.objects.for_clinic(clinic_id).get_or_create(
        community_group=invitation.community_group,
        user=cast(Any, user),
        defaults={
            "clinic_id": clinic_id,
            "role": invitation.role_offered,
            "pseudonym": pseudonym,
            "status": MembershipStatus.ACTIVE.value,
            "rules_accepted_version": invitation.community_group.rules_version,
            "rules_accepted_at": timezone.now(),
        },
    )
    if membership.status != MembershipStatus.ACTIVE.value:
        membership.status = MembershipStatus.ACTIVE.value
        membership.role = invitation.role_offered
        membership.pseudonym = pseudonym
        membership.left_at = None
        membership.save(
            update_fields=["status", "role", "pseudonym", "left_at", "updated_at"]
        )

    membership_joined.send(
        sender=CommunityMembership,
        group_id=invitation.community_group_id,
        user_id=user.pk,
    )
    return membership


@transaction.atomic
def join_community_group(
    *,
    clinic_id: UUID,
    group_id: UUID,
    user: AbstractBaseUser,
    pseudonym: str | None = None,
    user_age_tier: str | None = None,
) -> CommunityMembership:
    """Directly join an active tenant directory group after accepting its rules."""
    group = CommunityGroup.objects.for_clinic(clinic_id).get(id=group_id)
    if group.visibility == GroupVisibility.PRIVATE.value:
        raise PermissionError(
            "Cannot directly join a private group without an invitation."
        )
    if not can_join_group(user=user, group=group, user_age_tier=user_age_tier):
        raise PermissionError("User is not eligible to join this group.")

    membership, created = CommunityMembership.objects.for_clinic(
        clinic_id
    ).get_or_create(
        community_group=group,
        user=cast(Any, user),
        defaults={
            "clinic_id": clinic_id,
            "role": MembershipRole.MEMBER.value,
            "pseudonym": pseudonym,
            "status": MembershipStatus.ACTIVE.value,
            "rules_accepted_version": group.rules_version,
            "rules_accepted_at": timezone.now(),
        },
    )
    if not created:
        membership.status = MembershipStatus.ACTIVE.value
        membership.pseudonym = pseudonym
        membership.left_at = None
        membership.rules_accepted_version = group.rules_version
        membership.rules_accepted_at = timezone.now()
        membership.save(
            update_fields=[
                "status",
                "pseudonym",
                "left_at",
                "rules_accepted_version",
                "rules_accepted_at",
                "updated_at",
            ]
        )

    membership_joined.send(
        sender=CommunityMembership,
        group_id=group.id,
        user_id=user.pk,
    )
    return membership


@transaction.atomic
def leave_community_group(
    *,
    clinic_id: UUID,
    group_id: UUID,
    user: AbstractBaseUser,
) -> None:
    """Immediate voluntary exit from a community group ('saída imediata')."""
    membership = CommunityMembership.objects.for_clinic(clinic_id).get(
        community_group_id=group_id,
        user_id=user.pk,
    )
    membership.status = MembershipStatus.LEFT.value
    membership.left_at = timezone.now()
    membership.save(update_fields=["status", "left_at", "updated_at"])

    membership_left.send(
        sender=CommunityMembership,
        group_id=group_id,
        user_id=user.pk,
    )


@transaction.atomic
def close_community_group(
    *,
    clinic_id: UUID,
    group_id: UUID,
    closed_by: AbstractBaseUser,
) -> CommunityGroup:
    """Soft-delete / logically close a group with audit logging."""
    group = CommunityGroup.objects.for_clinic(clinic_id).get(id=group_id)
    if not can_moderate_group(user=closed_by, group=group):
        raise PermissionError("Only group owner or moderator can close the group.")

    group.is_active = False
    group.closed_at = timezone.now()
    group.closed_by = cast(Any, closed_by)
    group.save(update_fields=["is_active", "closed_at", "closed_by", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=closed_by.pk,
        action="communities.group_closed",
        resource_type="community_group",
        resource_id=str(group.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    community_group_closed.send(sender=CommunityGroup, group_id=group.id)
    return group

