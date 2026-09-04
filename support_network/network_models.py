"""Models for support network relationships and permissions (8.16.1)."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel
from support_network.contracts import InvitationStatus, RelationshipType

_ModelT = TypeVar("_ModelT", bound=models.Model)


class SupportNetworkQuerySet(models.QuerySet[_ModelT]):
    """Tenant-scoped query set for support network models."""

    def for_clinic(
        self: SupportNetworkQuerySet[_ModelT], clinic_id: UUID
    ) -> SupportNetworkQuerySet[_ModelT]:
        return self.filter(clinic_id=clinic_id)


class SupportNetworkTenantManager(models.Manager[_ModelT]):
    """Tenant-safe default manager requiring an explicit clinic scope."""

    def get_queryset(self) -> SupportNetworkQuerySet[_ModelT]:
        if hasattr(self, "core_filters") or hasattr(self, "instance"):
            return SupportNetworkQuerySet(self.model, using=self._db)
        raise RuntimeError("SupportNetwork queries require .for_clinic(clinic_id).")

    def for_clinic(
        self: SupportNetworkTenantManager[_ModelT], clinic_id: UUID
    ) -> SupportNetworkQuerySet[_ModelT]:
        return SupportNetworkQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureSupportNetworkManager(models.Manager[_ModelT]):
    """Unrestricted support network access for internal tasks and testing."""

    def get_queryset(
        self: InfrastructureSupportNetworkManager[_ModelT],
    ) -> SupportNetworkQuerySet[_ModelT]:
        return SupportNetworkQuerySet(self.model, using=self._db)


class SupportNetworkInvitation(UUIDTimestampedModel):
    """Granular invitation for trusted support network members."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="support_invitations",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="support_invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_support_invitations",
    )
    invitee_name = models.CharField(max_length=255)
    invitee_email = models.EmailField()
    invitee_phone = models.CharField(max_length=50, blank=True)
    relationship_type = models.CharField(
        max_length=50,
        choices=[(t.value, t.name) for t in RelationshipType],
        default=RelationshipType.FRIEND.value,
    )
    invitation_token = models.CharField(max_length=128, unique=True, db_index=True)
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.name) for s in InvitationStatus],
        default=InvitationStatus.PENDING.value,
        db_index=True,
    )
    permissions_offered = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_invitations"
        indexes = [
            models.Index(fields=["clinic", "patient", "status"]),
            models.Index(fields=["invitee_email", "status"]),
        ]

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


class SupportNetworkRelationship(UUIDTimestampedModel):
    """Active or historical support relationship between a patient and a supporter."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="support_relationships",
    )
    patient = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="support_relationships",
    )
    supporter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supported_patients",
    )
    supporter_name = models.CharField(max_length=255)
    supporter_email = models.EmailField()
    supporter_phone = models.CharField(max_length=50, blank=True)
    relationship_type = models.CharField(
        max_length=50,
        choices=[(t.value, t.name) for t in RelationshipType],
        default=RelationshipType.FRIEND.value,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    established_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_support_relationships",
    )

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_relationships"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "patient", "supporter_email"],
                condition=models.Q(is_active=True),
                name="unique_active_support_relationship",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "patient", "is_active"]),
            models.Index(fields=["supporter_email", "is_active"]),
        ]


class SupportNetworkPermission(UUIDTimestampedModel):
    """Granular permission scope assigned to a support relationship."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="support_permissions",
    )
    relationship = models.ForeignKey(
        SupportNetworkRelationship,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    permission_scope = models.CharField(max_length=100, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_support_permissions",
    )

    objects = SupportNetworkTenantManager()
    infrastructure_objects = InfrastructureSupportNetworkManager()

    class Meta:
        db_table = "support_network_permissions"
        constraints = [
            models.UniqueConstraint(
                fields=["relationship", "permission_scope"],
                condition=models.Q(is_active=True),
                name="unique_active_support_permission",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "permission_scope", "is_active"]),
        ]
