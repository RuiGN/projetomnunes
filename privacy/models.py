"""Tenant-scoped persistence for data-subject rights workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import models

from core.persistence import UUIDTimestampedModel


class PrivacyTenantScopeRequiredError(PermissionError):
    """Raised when privacy records are queried without an explicit tenant."""


class TenantScopedQuerySet(models.QuerySet[Any]):
    """Require a clinic scope before exposing privacy requests."""

    def for_clinic(self, clinic_id: UUID) -> TenantScopedQuerySet:
        """Return records that belong to one explicit clinic."""
        return self.filter(clinic_id=clinic_id)


class TenantScopedManager(models.Manager[Any]):
    """Reject implicit global reads through the common manager."""

    def get_queryset(self) -> TenantScopedQuerySet:
        """Prevent unscoped reads from the common application manager."""
        raise PrivacyTenantScopeRequiredError(
            "Privacy queries require an explicit clinic scope."
        )

    def for_clinic(self, clinic_id: UUID) -> TenantScopedQuerySet:
        """Create a tenant-scoped queryset from the infrastructure manager."""
        return TenantScopedQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class DataSubjectRequest(UUIDTimestampedModel):
    """One traceable LGPD request and its operational decision lifecycle."""

    class RequestType(models.TextChoices):
        CONFIRMATION = "confirmation", "Confirmação"
        ACCESS = "access", "Acesso"
        CORRECTION = "correction", "Correção"
        PORTABILITY = "portability", "Portabilidade"
        REVOCATION = "revocation", "Revogação"
        ERASURE = "erasure", "Eliminação"

    class Status(models.TextChoices):
        IDENTITY_PENDING = "identity_pending", "Identidade pendente"
        IN_REVIEW = "in_review", "Em análise"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"
        PROCESSING = "processing", "Em execução"
        COMPLETED = "completed", "Concluída"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="data_subject_requests",
    )
    subject_id = models.UUIDField(db_index=True)
    requested_by_id = models.UUIDField()
    assigned_to_id = models.UUIDField(null=True, blank=True)
    request_type = models.CharField(max_length=24, choices=RequestType.choices)
    channel = models.CharField(max_length=32)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.IDENTITY_PENDING,
    )
    requested_at = models.DateTimeField()
    due_at = models.DateTimeField()
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    identity_verification_method = models.CharField(max_length=32, blank=True)
    identity_evidence_digest = models.CharField(max_length=64, blank=True)
    identity_verified_by_id = models.UUIDField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_evidence_digest = models.CharField(max_length=64, blank=True)

    objects = TenantScopedManager()
    infrastructure_objects = models.Manager()

    class Meta:
        ordering = ("-requested_at", "id")
        indexes = (
            models.Index(fields=("clinic", "status", "due_at")),
            models.Index(fields=("clinic", "subject_id", "requested_at")),
        )


class ProcessingDestinationQuerySet(models.QuerySet[Any]):
    """Expose destinations only through a known parent request."""

    def for_request(
        self, *, clinic_id: UUID, request_id: UUID
    ) -> ProcessingDestinationQuerySet:
        """Scope propagation evidence to one request."""
        return self.filter(request_id=request_id, request__clinic_id=clinic_id)


class ProcessingDestinationManager(models.Manager[Any]):
    """Require the parent request scope for destination reads."""

    def get_queryset(self) -> ProcessingDestinationQuerySet:
        """Block global destination enumeration."""
        raise PrivacyTenantScopeRequiredError(
            "Processing destinations require an explicit request scope."
        )

    def for_request(
        self, *, clinic_id: UUID, request_id: UUID
    ) -> ProcessingDestinationQuerySet:
        """Return destinations associated with one request."""
        return ProcessingDestinationQuerySet(self.model, using=self._db).for_request(
            clinic_id=clinic_id,
            request_id=request_id,
        )


class ProcessingDestination(UUIDTimestampedModel):
    """Confirmation from each internal copy or integrated operator."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        CONFIRMED = "confirmed", "Confirmada"
        RETAINED = "retained", "Retida"
        FAILED = "failed", "Falhou"

    request = models.ForeignKey(
        DataSubjectRequest,
        on_delete=models.PROTECT,
        related_name="processing_destinations",
    )
    destination_key = models.CharField(max_length=128)
    adapter_identity = models.CharField(max_length=128, default="legacy.unrecorded")
    adapter_version = models.CharField(max_length=32, default="0")
    status = models.CharField(max_length=16, choices=Status.choices)
    confirmation_reference = models.CharField(max_length=255, blank=True)
    retained_reason = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    objects = ProcessingDestinationManager()
    infrastructure_objects = models.Manager()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("request", "destination_key"),
                name="privacy_unique_request_destination",
            ),
        )


class ExportArtifactQuerySet(models.QuerySet[Any]):
    """Expose export artifacts only under one explicit clinic."""

    def for_clinic(self, clinic_id: UUID) -> ExportArtifactQuerySet:
        return self.filter(request__clinic_id=clinic_id)


class ExportArtifactManager(models.Manager[Any]):
    """Reject global access to encrypted export artifacts."""

    def get_queryset(self) -> ExportArtifactQuerySet:
        raise PrivacyTenantScopeRequiredError(
            "Export artifacts require an explicit clinic scope."
        )

    def for_clinic(self, clinic_id: UUID) -> ExportArtifactQuerySet:
        return ExportArtifactQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class ExportArtifact(UUIDTimestampedModel):
    """Short-lived encrypted export whose key is carried by a signed grant."""

    request = models.OneToOneField(
        DataSubjectRequest,
        on_delete=models.PROTECT,
        related_name="export_artifact",
    )
    encrypted_payload = models.BinaryField()
    payload_digest = models.CharField(max_length=64)
    ciphertext_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()

    objects = ExportArtifactManager()
    infrastructure_objects = models.Manager()


class ReauthenticationProof(UUIDTimestampedModel):
    """Short-lived, one-use evidence of a verified actor credential."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="reauthentication_proofs",
    )
    actor_id = models.UUIDField(db_index=True)
    method = models.CharField(max_length=32, default="password")
    verified_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()
    infrastructure_objects = models.Manager()

    class Meta:
        indexes = (
            models.Index(
                fields=("clinic", "actor_id", "expires_at"),
                name="privacy_reauth_actor_exp_idx",
            ),
        )


@dataclass(frozen=True)
class LifecycleResult:
    """Normalized result returned by a data-lifecycle destination adapter."""

    destination_key: str
    outcome: str
    confirmation_reference: str
    retained_reason: str = ""
