"""White label, custom domain, and communication template persistence models."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.db import models

from core.persistence import UUIDTimestampedModel


class TenantScopeRequiredError(RuntimeError):
    """Raised when tenant-owned white-label records are queried without a clinic ID."""


# ---------------------------------------------------------------------------
# Brand theme versioning
# ---------------------------------------------------------------------------


class BrandThemeVersionQuerySet(models.QuerySet["BrandThemeVersion"]):
    def for_clinic(self, clinic_id: UUID) -> BrandThemeVersionQuerySet:
        return self.filter(clinic_id=clinic_id)


class BrandThemeVersionManager(models.Manager["BrandThemeVersion"]):
    def get_queryset(self) -> NoReturn:
        raise TenantScopeRequiredError(
            "BrandThemeVersion queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> BrandThemeVersionQuerySet:
        return BrandThemeVersionQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureBrandThemeVersionManager(models.Manager["BrandThemeVersion"]):
    def get_queryset(self) -> BrandThemeVersionQuerySet:
        return BrandThemeVersionQuerySet(self.model, using=self._db)


class BrandThemeVersion(UUIDTimestampedModel):
    """Versioned snapshot of brand tokens for preview, audit, and rollback."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="theme_versions",
    )
    version = models.PositiveIntegerField()
    tokens = models.JSONField(default=dict)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="brand_theme_versions_created",
    )

    objects = BrandThemeVersionManager()
    infrastructure_objects = InfrastructureBrandThemeVersionManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "version"),
                name="unique_brand_theme_version_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "version"),
                name="brand_theme_ver_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.clinic_id} theme v{self.version}"


# ---------------------------------------------------------------------------
# Custom domains
# ---------------------------------------------------------------------------


class CustomDomainQuerySet(models.QuerySet["CustomDomain"]):
    def for_clinic(self, clinic_id: UUID) -> CustomDomainQuerySet:
        return self.filter(clinic_id=clinic_id)


class CustomDomainManager(models.Manager["CustomDomain"]):
    def get_queryset(self) -> NoReturn:
        raise TenantScopeRequiredError(
            "CustomDomain queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> CustomDomainQuerySet:
        return CustomDomainQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureCustomDomainManager(models.Manager["CustomDomain"]):
    def get_queryset(self) -> CustomDomainQuerySet:
        return CustomDomainQuerySet(self.model, using=self._db)


class CustomDomain(UUIDTimestampedModel):
    """A custom domain mapped to one clinic with verified ownership and TLS state."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        VERIFIED = "verified", "Verificado"
        ACTIVE = "active", "Ativo"
        FAILED = "failed", "Falhou"
        REVOKED = "revoked", "Revogado"

    class TlsStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        ACTIVE = "active", "Ativo"
        RENEWAL_DUE = "renewal_due", "Renovação Pendente"
        FAILED = "failed", "Falhou"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="custom_domains",
    )
    domain = models.CharField(max_length=253, unique=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    verification_token = models.CharField(max_length=64)
    verified_at = models.DateTimeField(null=True, blank=True)
    tls_status = models.CharField(
        max_length=16, choices=TlsStatus.choices, default=TlsStatus.PENDING
    )
    tls_provisioned_at = models.DateTimeField(null=True, blank=True)
    tls_expires_at = models.DateTimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custom_domains_created",
    )

    objects = CustomDomainManager()
    infrastructure_objects = InfrastructureCustomDomainManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(fields=("clinic", "status"), name="custom_domain_status_idx"),
            models.Index(fields=("domain",), name="custom_domain_lookup_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.domain} ({self.status})"


# ---------------------------------------------------------------------------
# Communication templates
# ---------------------------------------------------------------------------


class CommunicationTemplateQuerySet(models.QuerySet["CommunicationTemplate"]):
    def for_clinic(self, clinic_id: UUID) -> CommunicationTemplateQuerySet:
        return self.filter(clinic_id=clinic_id)


class CommunicationTemplateManager(models.Manager["CommunicationTemplate"]):
    def get_queryset(self) -> NoReturn:
        raise TenantScopeRequiredError(
            "CommunicationTemplate queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> CommunicationTemplateQuerySet:
        return CommunicationTemplateQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureCommunicationTemplateManager(
    models.Manager["CommunicationTemplate"]
):
    def get_queryset(self) -> CommunicationTemplateQuerySet:
        return CommunicationTemplateQuerySet(self.model, using=self._db)


class CommunicationTemplate(UUIDTimestampedModel):
    """Versioned transactional communication template for email,
    notification, and public-page channels."""

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        NOTIFICATION = "notification", "Notificação"
        PUBLIC_PAGE = "public_page", "Página Pública"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_REVIEW = "in_review", "Em Revisão"
        ACTIVE = "active", "Ativo"
        ARCHIVED = "archived", "Arquivado"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="communication_templates",
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    purpose = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(max_length=20000)
    allowed_variables = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comm_templates_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comm_templates_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = CommunicationTemplateManager()
    infrastructure_objects = InfrastructureCommunicationTemplateManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("channel", "purpose", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "channel", "purpose", "version"),
                name="unique_template_version_per_clinic",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "channel", "purpose", "status"),
                name="comm_template_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.purpose} v{self.version} ({self.status})"
