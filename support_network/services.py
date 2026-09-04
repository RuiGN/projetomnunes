"""Services for support network invitations and permissions (8.16.1)."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService
from support_network.contracts import (
    FORBIDDEN_SUPPORT_SCOPES,
    InvitationStatus,
    RelationshipType,
    SupportPermissionScope,
)
from support_network.events import (
    invitation_accepted,
    invitation_created,
    invitation_declined,
    invitation_revoked,
    permission_updated,
    relationship_revoked,
)
from support_network.network_models import (
    SupportNetworkInvitation,
    SupportNetworkPermission,
    SupportNetworkRelationship,
)


class Service(CoreService[Any, Any]):
    """Support network domain service base."""


@transaction.atomic
def create_support_invitation(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    invitee_name: str,
    invitee_email: str,
    invitee_phone: str = "",
    relationship_type: str = RelationshipType.FRIEND.value,
    permissions_offered: list[str] | None = None,
    expiry_days: int = 7,
    invited_by: AbstractBaseUser | None = None,
    actor_id: UUID | None = None,
) -> SupportNetworkInvitation:
    """Create a new granular support invitation for a trusted individual."""
    permissions = permissions_offered or [
        SupportPermissionScope.VIEW_WELLNESS_SUMMARY.value,
        SupportPermissionScope.RECEIVE_URGENT_ALERTS.value,
    ]

    for scope in permissions:
        if scope.lower() in FORBIDDEN_SUPPORT_SCOPES:
            raise ValueError(
                f"Permissão '{scope}' não pode ser compartilhada com rede de apoio. "
                "Prontuário, mensagens e instrumentos clínicos são sigilosos."
            )

    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(days=expiry_days)

    invitation = SupportNetworkInvitation.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
        invited_by=cast(Any, invited_by),
        invitee_name=invitee_name.strip(),
        invitee_email=invitee_email.strip().lower(),
        invitee_phone=invitee_phone.strip(),
        relationship_type=relationship_type,
        invitation_token=token,
        status=InvitationStatus.PENDING.value,
        permissions_offered=permissions,
        expires_at=expires_at,
    )

    invitation_created.send(sender=SupportNetworkInvitation, invitation=invitation)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or (invited_by.pk if invited_by else None),
        action="support_network.invitation_created",
        resource_type="support_invitation",
        resource_id=str(invitation.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return invitation


@transaction.atomic
def accept_support_invitation(
    *,
    clinic_id: UUID,
    invitation_token: str,
    supporter_user: AbstractBaseUser | None = None,
    actor_id: UUID | None = None,
) -> SupportNetworkRelationship:
    """Accept active invitation and materialize support relationship."""
    now = timezone.now()
    invitation = (
        SupportNetworkInvitation.objects.for_clinic(clinic_id)
        .filter(invitation_token=invitation_token)
        .first()
    )
    if not invitation:
        raise ValueError("Convite não encontrado.")

    if invitation.status != InvitationStatus.PENDING.value:
        raise ValueError(
            f"Convite não está pendente (status atual: {invitation.status})."
        )

    if invitation.is_expired():
        invitation.status = InvitationStatus.EXPIRED.value
        invitation.save(update_fields=["status", "updated_at"])
        raise ValueError("Convite expirado.")

    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.accepted_at = now
    invitation.save(update_fields=["status", "accepted_at", "updated_at"])

    # Create or reactivate relationship
    relationship, _ = SupportNetworkRelationship.objects.for_clinic(
        clinic_id
    ).update_or_create(
        clinic_id=clinic_id,
        patient_id=invitation.patient_id,
        supporter_email=invitation.invitee_email,
        defaults={
            "supporter_user": cast(Any, supporter_user),
            "supporter_name": invitation.invitee_name,
            "supporter_phone": invitation.invitee_phone,
            "relationship_type": invitation.relationship_type,
            "is_active": True,
            "established_at": now,
            "revoked_at": None,
            "revoked_by": None,
        },
    )

    # Establish permissions
    for scope in invitation.permissions_offered:
        if scope.lower() not in FORBIDDEN_SUPPORT_SCOPES:
            SupportNetworkPermission.objects.for_clinic(clinic_id).update_or_create(
                clinic_id=clinic_id,
                relationship=relationship,
                permission_scope=scope,
                defaults={
                    "is_active": True,
                    "granted_at": now,
                    "revoked_at": None,
                    "revoked_by": None,
                },
            )

    invitation_accepted.send(
        sender=SupportNetworkRelationship,
        relationship=relationship,
        invitation=invitation,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or (supporter_user.pk if supporter_user else None),
        action="support_network.invitation_accepted",
        resource_type="support_relationship",
        resource_id=str(relationship.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return relationship


@transaction.atomic
def decline_support_invitation(
    *,
    clinic_id: UUID,
    invitation_token: str,
    actor_id: UUID | None = None,
) -> SupportNetworkInvitation:
    """Explicitly decline a received support invitation."""
    invitation = (
        SupportNetworkInvitation.objects.for_clinic(clinic_id)
        .filter(invitation_token=invitation_token)
        .first()
    )
    if not invitation:
        raise ValueError("Convite não encontrado.")

    if invitation.status != InvitationStatus.PENDING.value:
        raise ValueError("Convite não está pendente.")

    invitation.status = InvitationStatus.DECLINED.value
    invitation.declined_at = timezone.now()
    invitation.save(update_fields=["status", "declined_at", "updated_at"])

    invitation_declined.send(sender=SupportNetworkInvitation, invitation=invitation)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.invitation_declined",
        resource_type="support_invitation",
        resource_id=str(invitation.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return invitation


@transaction.atomic
def revoke_support_invitation(
    *,
    clinic_id: UUID,
    invitation_id: UUID,
    revoked_by: AbstractBaseUser | None = None,
    actor_id: UUID | None = None,
) -> SupportNetworkInvitation:
    """Revoke an active pending invitation before acceptance."""
    invitation = (
        SupportNetworkInvitation.objects.for_clinic(clinic_id)
        .filter(id=invitation_id)
        .first()
    )
    if not invitation:
        raise ValueError("Convite não encontrado.")

    invitation.status = InvitationStatus.REVOKED.value
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["status", "revoked_at", "updated_at"])

    invitation_revoked.send(sender=SupportNetworkInvitation, invitation=invitation)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or (revoked_by.pk if revoked_by else None),
        action="support_network.invitation_revoked",
        resource_type="support_invitation",
        resource_id=str(invitation.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return invitation


@transaction.atomic
def revoke_support_relationship(
    *,
    clinic_id: UUID,
    relationship_id: UUID,
    revoked_by: AbstractBaseUser,
    actor_id: UUID | None = None,
) -> SupportNetworkRelationship:
    """Terminate a supporter's active status and revoke all permissions."""
    now = timezone.now()
    relationship = (
        SupportNetworkRelationship.objects.for_clinic(clinic_id)
        .filter(id=relationship_id)
        .first()
    )
    if not relationship:
        raise ValueError("Vínculo de apoio não encontrado.")

    relationship.is_active = False
    relationship.revoked_at = now
    relationship.revoked_by = cast(Any, revoked_by)
    relationship.save(
        update_fields=["is_active", "revoked_at", "revoked_by", "updated_at"]
    )

    # Revoke all active permissions under this relationship
    SupportNetworkPermission.objects.for_clinic(clinic_id).filter(
        relationship=relationship, is_active=True
    ).update(
        is_active=False,
        revoked_at=now,
        revoked_by=cast(Any, revoked_by),
        updated_at=now,
    )

    relationship_revoked.send(
        sender=SupportNetworkRelationship, relationship=relationship
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or revoked_by.pk,
        action="support_network.relationship_revoked",
        resource_type="support_relationship",
        resource_id=str(relationship.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return relationship


@transaction.atomic
def update_support_permissions(
    *,
    clinic_id: UUID,
    relationship_id: UUID,
    granted_scopes: set[str],
    user: AbstractBaseUser,
    step_up_authenticated: bool = False,
    actor_id: UUID | None = None,
) -> list[SupportNetworkPermission]:
    """Update granular permissions for a supporter.

    SECURITY REQUIREMENT: Requires step-up authentication confirmation.
    """
    if not step_up_authenticated:
        raise PermissionDenied(
            "Alteração de permissões sensíveis da rede de apoio requer reautenticação "
            "ou confirmação reforçada de segurança."
        )

    for scope in granted_scopes:
        if scope.lower() in FORBIDDEN_SUPPORT_SCOPES:
            raise ValueError(
                f"Permissão '{scope}' é estritamente proibida para rede de apoio."
            )

    relationship = (
        SupportNetworkRelationship.objects.for_clinic(clinic_id)
        .filter(id=relationship_id, is_active=True)
        .first()
    )
    if not relationship:
        raise ValueError("Vínculo de apoio ativo não encontrado.")

    now = timezone.now()
    # Revoke scopes not in granted_scopes
    SupportNetworkPermission.objects.for_clinic(clinic_id).filter(
        relationship=relationship, is_active=True
    ).exclude(permission_scope__in=granted_scopes).update(
        is_active=False,
        revoked_at=now,
        revoked_by=cast(Any, user),
        updated_at=now,
    )

    # Add or reactivate granted scopes
    result_permissions: list[SupportNetworkPermission] = []
    for scope in granted_scopes:
        perm, _ = SupportNetworkPermission.objects.for_clinic(
            clinic_id
        ).update_or_create(
            clinic_id=clinic_id,
            relationship=relationship,
            permission_scope=scope,
            defaults={
                "is_active": True,
                "granted_at": now,
                "revoked_at": None,
                "revoked_by": None,
            },
        )
        result_permissions.append(perm)

    permission_updated.send(
        sender=SupportNetworkRelationship,
        relationship=relationship,
        scopes=list(granted_scopes),
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or user.pk,
        action="support_network.permissions_updated",
        resource_type="support_relationship",
        resource_id=str(relationship.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return result_permissions


__all__ = [
    "Service",
    "accept_support_invitation",
    "create_support_invitation",
    "decline_support_invitation",
    "revoke_support_invitation",
    "revoke_support_relationship",
    "update_support_permissions",
]
