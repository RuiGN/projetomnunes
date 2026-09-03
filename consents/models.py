"""Tenant-scoped versioned consent documents and manifestations."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from core.persistence import UUIDTimestampedModel


class ConsentTenantScopeRequiredError(RuntimeError):
    """Raised when consent data is queried without an explicit clinic scope."""


class ConsentTenantQuerySet(models.QuerySet[Any]):
    """Composable consent queries retaining an explicit tenant filter."""

    def for_clinic(self, clinic_id: UUID) -> ConsentTenantQuerySet:
        return self.filter(clinic_id=clinic_id)


class AppendOnlyConsentQuerySet(ConsentTenantQuerySet):
    """Permit scoped reads while rejecting destructive bulk operations."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations are append-only.")

    def delete(self) -> NoReturn:
        raise PermissionDenied("Consent manifestations are append-only.")

    def bulk_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations require the consent service.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations are append-only.")

    def get_or_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations require the consent service.")

    def update_or_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations require the consent service.")


class ImmutableDocumentQuerySet(ConsentTenantQuerySet):
    """Reject bulk mutation of versioned legal documents."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Published consent documents are immutable.")

    def delete(self) -> NoReturn:
        raise PermissionDenied("Published consent documents are immutable.")

    def bulk_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent documents require the publication service.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Published consent documents are immutable.")

    def get_or_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent documents require the publication service.")

    def update_or_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent documents require the publication service.")


class ProtectedLifecycleConsentQuerySet(ConsentTenantQuerySet):
    """Allow reads and inserts while reserving lifecycle mutation for services."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Protected consent records require a lifecycle service.")

    def delete(self) -> NoReturn:
        raise PermissionDenied("Protected consent records cannot be deleted.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Protected consent records require a lifecycle service.")

    def update_or_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Protected consent records require a lifecycle service.")


class ScopedAppendOnlyConsentQuerySet(AppendOnlyConsentQuerySet):
    """Public tenant scope that only permits reads."""

    def create(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations require the consent service.")


class ScopedImmutableDocumentQuerySet(ImmutableDocumentQuerySet):
    """Public tenant scope that only permits reads."""

    def create(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent documents require the publication service.")


class ScopedProtectedLifecycleConsentQuerySet(ProtectedLifecycleConsentQuerySet):
    """Expose tenant-scoped reads without permitting direct record creation."""

    def create(self, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Protected consent records require a lifecycle service.")


class ConsentTenantManager(models.Manager[Any]):
    """Reject unscoped application reads of consent data."""

    def get_queryset(self) -> NoReturn:
        raise ConsentTenantScopeRequiredError(
            "Consent queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ConsentTenantQuerySet:
        return ConsentTenantQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class AppendOnlyConsentManager(ConsentTenantManager):
    """Tenant-scoped manager backed by an append-only queryset."""

    def for_clinic(self, clinic_id: UUID) -> ScopedAppendOnlyConsentQuerySet:
        queryset = ScopedAppendOnlyConsentQuerySet(self.model, using=self._db)
        return queryset.filter(clinic_id=clinic_id)


class ImmutableDocumentManager(ConsentTenantManager):
    """Tenant-scoped manager backed by an immutable queryset."""

    def for_clinic(self, clinic_id: UUID) -> ScopedImmutableDocumentQuerySet:
        queryset = ScopedImmutableDocumentQuerySet(self.model, using=self._db)
        return queryset.filter(clinic_id=clinic_id)


class ProtectedLifecycleConsentManager(ConsentTenantManager):
    """Tenant-scoped read manager for service-owned lifecycle records."""

    def for_clinic(self, clinic_id: UUID) -> ScopedProtectedLifecycleConsentQuerySet:
        queryset = ScopedProtectedLifecycleConsentQuerySet(self.model, using=self._db)
        return queryset.filter(clinic_id=clinic_id)


class RevocationWorkItemManager(ConsentTenantManager):
    """Scope operational work through its authoritative dispatch tenant."""

    def for_clinic(self, clinic_id: UUID) -> ScopedProtectedLifecycleConsentQuerySet:
        queryset = ScopedProtectedLifecycleConsentQuerySet(self.model, using=self._db)
        return queryset.filter(dispatch__clinic_id=clinic_id)


class InfrastructureDocumentManager(models.Manager[Any]):
    """Allow framework reads and inserts without destructive bulk operations."""

    def get_queryset(self) -> ImmutableDocumentQuerySet:
        return ImmutableDocumentQuerySet(self.model, using=self._db)


class InfrastructureManifestationManager(models.Manager[Any]):
    """Allow framework reads and appends without destructive bulk operations."""

    def get_queryset(self) -> AppendOnlyConsentQuerySet:
        return AppendOnlyConsentQuerySet(self.model, using=self._db)


class InfrastructureProtectedLifecycleManager(models.Manager[Any]):
    """Permit inserts and locks while blocking ordinary bulk mutation/deletion."""

    def get_queryset(self) -> ProtectedLifecycleConsentQuerySet:
        return ProtectedLifecycleConsentQuerySet(self.model, using=self._db)


class ConsentDocument(UUIDTimestampedModel):
    """One immutable published version of a tenant-owned legal document."""

    class DocumentType(models.TextChoices):
        TERMS = "terms", "Termos de uso"
        PRIVACY_NOTICE = "privacy_notice", "Aviso de privacidade"
        CLINICAL_LIMITS = "clinical_limits", "Ciência de limites"
        CONSENT = "consent", "Consentimento"

    class Audience(models.TextChoices):
        ALL = "all", "Todos"
        PATIENT = "patient", "Pacientes"
        PROFESSIONAL = "professional", "Profissionais"
        ADMINISTRATIVE = "administrative", "Equipe administrativa"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="consent_documents",
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    title = models.CharField(max_length=255)
    version = models.CharField(max_length=32)
    content = models.TextField()
    purpose = models.CharField(max_length=100)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    audience = models.CharField(max_length=24, choices=Audience.choices)
    is_mandatory = models.BooleanField(default=False)
    refusal_consequence = models.TextField()
    alternative_instructions = models.TextField()
    clinic_contact_instructions = models.TextField()
    is_active = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    publication_hash = models.CharField(max_length=64, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_consent_documents",
        null=True,
        blank=True,
    )

    objects = ImmutableDocumentManager()
    infrastructure_objects = InfrastructureDocumentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.UniqueConstraint(
                fields=("clinic", "document_type", "purpose", "audience", "version"),
                name="consent_unique_document_version",
            ),
        )
        indexes = (
            models.Index(
                fields=("clinic", "audience", "is_active", "effective_from"),
                name="consent_doc_current_idx",
            ),
        )

    def clean(self) -> None:
        """Validate purpose classification even outside publication services."""
        super().clean()
        from .policies import (
            PurposeClassification,
            document_type_for_purpose,
            purpose_definition,
        )

        try:
            definition = purpose_definition(self.purpose)
        except (KeyError, ValueError) as exc:
            raise ValidationError(
                {"purpose": "Finalidade de consentimento não cadastrada."}
            ) from exc
        if definition.classification is PurposeClassification.BASIC_RIGHT:
            raise ValidationError(
                {"purpose": "Direitos básicos não podem depender de consentimento."}
            )
        if self.is_mandatory is not definition.is_mandatory:
            raise ValidationError(
                {
                    "is_mandatory": (
                        "A obrigatoriedade deve corresponder à classificação "
                        "da finalidade."
                    )
                }
            )
        if self.document_type != document_type_for_purpose(self.purpose):
            raise ValidationError(
                {
                    "document_type": (
                        "O tipo do documento deve corresponder à finalidade."
                    )
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Prevent silent mutation of the canonical published document payload."""
        if not self._state.adding:
            persisted = ConsentDocument.infrastructure_objects.get(pk=self.pk)
            immutable_fields = (
                "clinic_id",
                "document_type",
                "title",
                "version",
                "content",
                "purpose",
                "effective_from",
                "effective_until",
                "audience",
                "is_mandatory",
                "refusal_consequence",
                "alternative_instructions",
                "clinic_contact_instructions",
                "is_active",
                "published_at",
                "publication_hash",
                "published_by_id",
            )
            if persisted.published_at is not None and any(
                getattr(self, field) != getattr(persisted, field)
                for field in immutable_fields
            ):
                raise ValidationError(
                    "Documentos publicados não podem ser alterados; "
                    "publique uma nova versão."
                )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Published consent documents cannot be deleted.")


class ConsentManifestation(UUIDTimestampedModel):
    """Evidence of one decision against an exact published document version."""

    class Decision(models.TextChoices):
        ACCEPTED = "accepted", "Aceitou"
        REFUSED = "refused", "Recusou"
        REVOKED = "revoked", "Revogou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="consent_manifestations",
    )
    document = models.ForeignKey(
        ConsentDocument,
        on_delete=models.PROTECT,
        related_name="manifestations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consent_actions",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consent_manifestations",
    )
    represented_subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="represented_consent_manifestations",
        null=True,
        blank=True,
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    purpose = models.CharField(max_length=100)
    document_hash = models.CharField(max_length=64)
    evidence_digest = models.CharField(max_length=64)
    revocation_reason_digest = models.CharField(max_length=64, blank=True)
    representation_evidence_digest = models.CharField(max_length=64, blank=True)
    manifested_at = models.DateTimeField()
    sequence = models.PositiveIntegerField()
    request_id = models.UUIDField()
    source = models.CharField(max_length=32, default="web")

    objects = AppendOnlyConsentManager()
    infrastructure_objects = InfrastructureManifestationManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = (
            models.Index(
                fields=("clinic", "subject", "purpose", "manifested_at"),
                name="consent_subject_purpose_idx",
            ),
        )
        constraints = (
            models.UniqueConstraint(
                fields=("clinic", "request_id"),
                name="consent_unique_manifestation_request",
            ),
            models.UniqueConstraint(
                fields=("clinic", "document", "subject", "sequence"),
                name="consent_unique_subject_sequence",
            ),
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionDenied("Consent manifestations are append-only.")
        if self.document_id and self.clinic_id != self.document.clinic_id:
            raise ValidationError(
                "A manifestação e o documento devem pertencer à mesma clínica."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Consent manifestations are append-only.")


class ConsentRevocationDispatch(UUIDTimestampedModel):
    """Server-owned delivery obligation created by a consent revocation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        CONFIRMED = "confirmed", "Confirmado"
        FAILED = "failed", "Falhou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="consent_revocation_dispatches",
    )
    manifestation = models.ForeignKey(
        ConsentManifestation,
        on_delete=models.PROTECT,
        related_name="revocation_dispatches",
    )
    destination = models.CharField(max_length=100)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_digest = models.CharField(max_length=64, blank=True)
    failure_digest = models.CharField(max_length=64, blank=True)
    adapter_identity = models.CharField(max_length=100, blank=True)
    adapter_version = models.CharField(max_length=32, blank=True)

    objects = ProtectedLifecycleConsentManager()
    infrastructure_objects = InfrastructureProtectedLifecycleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.UniqueConstraint(
                fields=("clinic", "manifestation", "destination"),
                name="consent_unique_revocation_destination",
            ),
        )
        indexes = (
            models.Index(
                fields=("clinic", "status", "created_at"),
                name="consent_revocation_queue_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if self.manifestation_id and (
            self.clinic_id != self.manifestation.clinic_id
            or self.manifestation.decision != ConsentManifestation.Decision.REVOKED
        ):
            raise ValidationError(
                "O despacho deve pertencer à mesma clínica e a uma revogação."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow initial persistence only; services own later lifecycle changes."""
        if not self._state.adding:
            raise PermissionDenied("Dispatch obligations require a lifecycle service.")
        super().save(*args, **kwargs)

    def _save_lifecycle_transition(self, *, update_fields: tuple[str, ...]) -> None:
        """Persist a transition already authorized by the consent service."""
        super().save(update_fields=(*update_fields, "updated_at"))

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Dispatch obligations cannot be deleted.")


class ConsentRevocationWorkItem(UUIDTimestampedModel):
    """Durable clinic-operations work requiring explicit acknowledgement."""

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        ACKNOWLEDGED = "acknowledged", "Reconhecida"

    dispatch = models.OneToOneField(
        ConsentRevocationDispatch,
        on_delete=models.PROTECT,
        related_name="operational_work_item",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="acknowledged_consent_revocation_work_items",
        null=True,
        blank=True,
    )
    acknowledgement_digest = models.CharField(max_length=64, blank=True)

    objects = RevocationWorkItemManager()
    infrastructure_objects = InfrastructureProtectedLifecycleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = (
            models.Index(
                fields=("status", "created_at"),
                name="consent_work_item_queue_idx",
            ),
        )
        constraints = (
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="open",
                        acknowledged_at__isnull=True,
                        acknowledged_by__isnull=True,
                        acknowledgement_digest="",
                    )
                    | (
                        models.Q(
                            status="acknowledged",
                            acknowledged_at__isnull=False,
                            acknowledged_by__isnull=False,
                        )
                        & ~models.Q(acknowledgement_digest="")
                    )
                ),
                name="consent_work_item_ack_evidence_ck",
            ),
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionDenied("Work items require an acknowledgement service.")
        super().save(*args, **kwargs)

    def _save_acknowledgement(self) -> None:
        """Persist the one service-authorized acknowledgement transition."""
        super().save(
            update_fields=(
                "status",
                "acknowledged_at",
                "acknowledged_by",
                "acknowledgement_digest",
                "updated_at",
            )
        )

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Work items cannot be deleted.")


class ConsentRevocationDispatchAttempt(UUIDTimestampedModel):
    """Immutable evidence from one execution of a revocation destination."""

    class Outcome(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmado"
        FAILED = "failed", "Falhou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="consent_revocation_dispatch_attempts",
    )
    dispatch = models.ForeignKey(
        ConsentRevocationDispatch,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    attempt_number = models.PositiveIntegerField()
    outcome = models.CharField(max_length=16, choices=Outcome)
    adapter_identity = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=32)
    evidence_digest = models.CharField(max_length=64)

    objects = AppendOnlyConsentManager()
    infrastructure_objects = InfrastructureManifestationManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.UniqueConstraint(
                fields=("dispatch", "attempt_number"),
                name="consent_unique_dispatch_attempt",
            ),
        )
        indexes = (
            models.Index(
                fields=("clinic", "dispatch", "attempt_number"),
                name="consent_dispatch_attempt_idx",
            ),
        )

    def clean(self) -> None:
        super().clean()
        if not self.evidence_digest:
            raise ValidationError("A evidência da tentativa é obrigatória.")
        if self.dispatch_id and self.clinic_id != self.dispatch.clinic_id:
            raise ValidationError("A tentativa e o despacho devem pertencer à clínica.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionDenied("Dispatch attempts are append-only.")
        if not self.evidence_digest:
            raise ValidationError("A evidência da tentativa é obrigatória.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Dispatch attempts are append-only.")


class LegalRepresentation(UUIDTimestampedModel):
    """Administratively verified, bounded authority to act for one subject."""

    class RelationshipType(models.TextChoices):
        LEGAL_GUARDIAN = "legal_guardian", "Responsável legal"
        COURT_APPOINTED_GUARDIAN = "court_guardian", "Curador judicial"
        AUTHORIZED_REPRESENTATIVE = "authorized_representative", "Procurador"

    class Status(models.TextChoices):
        VERIFIED = "verified", "Verificada"
        SUSPENDED = "suspended", "Suspensa"
        EXPIRED = "expired", "Expirada"
        REVOKED = "revoked", "Revogada"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="legal_representations",
    )
    representative = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legal_representations_granted",
    )
    represented_subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legal_representations_received",
    )
    relationship_type = models.CharField(max_length=32, choices=RelationshipType)
    granted_purposes = models.JSONField(default=list)
    evidence_digest = models.CharField(max_length=64)
    valid_from = models.DateField()
    valid_until = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.VERIFIED,
    )
    verified_at = models.DateTimeField()
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legal_representations_verified",
    )
    next_review_at = models.DateField()
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    objects = ProtectedLifecycleConsentManager()
    infrastructure_objects = InfrastructureProtectedLifecycleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(representative=models.F("represented_subject")),
                name="consent_representation_distinct_people",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gte=models.F("valid_from")),
                name="consent_representation_valid_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(next_review_at__lte=models.F("valid_until")),
                name="consent_representation_review_within_validity",
            ),
        )
        indexes = (
            models.Index(
                fields=(
                    "clinic",
                    "representative",
                    "represented_subject",
                    "status",
                ),
                name="consent_repr_access_idx",
            ),
            models.Index(
                fields=("clinic", "status", "next_review_at"),
                name="consent_repr_review_idx",
            ),
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Keep evidence and granted powers immutable after initial verification."""
        if not self._state.adding:
            raise PermissionDenied(
                "Legal representations require an audited lifecycle service."
            )
        super().save(*args, **kwargs)

    def _save_lifecycle_transition(self, *, update_fields: tuple[str, ...]) -> None:
        """Persist only a service-authorized status/review transition."""
        super().save(update_fields=(*update_fields, "updated_at"))

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Legal representations cannot be deleted.")


class AccessReviewRun(UUIDTimestampedModel):
    """Immutable persisted identity for one tenant access review date."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="access_review_runs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_access_reviews",
    )
    review_date = models.DateField()
    reviewed_at = models.DateTimeField()

    objects = ProtectedLifecycleConsentManager()
    infrastructure_objects = InfrastructureProtectedLifecycleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.UniqueConstraint(
                fields=("clinic", "review_date"),
                name="consent_unique_access_review_date",
            ),
        )
        indexes = (
            models.Index(
                fields=("clinic", "-review_date"),
                name="consent_access_review_run_idx",
            ),
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionDenied("Access review runs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Access review runs cannot be deleted.")


class AccessReviewException(UUIDTimestampedModel):
    """Persisted, deduplicated exception that operators can resolve explicitly."""

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        RESOLVED = "resolved", "Resolvida"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.PROTECT,
        related_name="access_review_exceptions",
    )
    first_run = models.ForeignKey(
        AccessReviewRun,
        on_delete=models.PROTECT,
        related_name="first_seen_exceptions",
    )
    last_seen_run = models.ForeignKey(
        AccessReviewRun,
        on_delete=models.PROTECT,
        related_name="last_seen_exceptions",
    )
    resource_type = models.CharField(max_length=100)
    resource_id = models.UUIDField()
    reason = models.CharField(max_length=100)
    action = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_access_review_exceptions",
        null=True,
        blank=True,
    )
    resolution_digest = models.CharField(max_length=64, blank=True)

    objects = ProtectedLifecycleConsentManager()
    infrastructure_objects = InfrastructureProtectedLifecycleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = (
            models.UniqueConstraint(
                fields=("clinic", "resource_type", "resource_id", "reason"),
                name="consent_unique_access_exception",
            ),
        )
        indexes = (
            models.Index(
                fields=("clinic", "status", "created_at"),
                name="consent_access_exception_idx",
            ),
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionDenied(
                "Access review exceptions require a lifecycle service."
            )
        super().save(*args, **kwargs)

    def _save_lifecycle_transition(self, *, update_fields: tuple[str, ...]) -> None:
        """Persist one explicit resolution or last-seen transition."""
        super().save(update_fields=(*update_fields, "updated_at"))

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise PermissionDenied("Access review exceptions cannot be deleted.")
