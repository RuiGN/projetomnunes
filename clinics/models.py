"""Clinic tenant and membership persistence models."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from core.persistence import UUIDTimestampedModel


class TenantScopeRequiredError(RuntimeError):
    """Raised when tenant-owned records are queried without a clinic ID."""


def clinic_logo_upload_to(instance: ClinicConfiguration, filename: str) -> str:
    """Build a tenant-owned opaque logo path without retaining user filenames."""
    suffix = Path(filename).suffix.lower()
    clinic_id = cast(Any, instance).clinic_id
    return f"clinics/{clinic_id}/branding/{uuid4().hex}{suffix}"


class ClinicQuerySet(models.QuerySet["Clinic"]):
    """Explicitly scoped clinic queries used by trusted tenant resolution."""

    def for_clinic(self, clinic_id: UUID) -> ClinicQuerySet:
        """Restrict discovery to one explicit clinic identifier."""
        return self.filter(pk=clinic_id)


class ClinicManager(models.Manager["Clinic"]):
    """Default manager that refuses global clinic enumeration."""

    def get_queryset(self) -> NoReturn:
        """Reject an unscoped public query."""
        raise TenantScopeRequiredError("Clinic queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ClinicQuerySet:
        """Return the one explicitly selected clinic, if it exists."""
        return ClinicQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureClinicManager(models.Manager["Clinic"]):
    """Unrestricted clinic access reserved for resolution and administration."""

    def get_queryset(self) -> ClinicQuerySet:
        """Return the unrestricted infrastructure queryset."""
        return ClinicQuerySet(self.model, using=self._db)


class Clinic(UUIDTimestampedModel):
    """Tenant root for one clinic."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=63, unique=True)
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False)

    objects = ClinicManager()
    infrastructure_objects = InfrastructureClinicManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                Lower("slug"),
                name="unique_clinic_slug_case_insensitive",
            ),
            models.CheckConstraint(
                condition=Q(slug__regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z"),
                name="clinic_slug_canonical_ascii_lowercase",
            ),
        ]
        indexes = [
            models.Index(fields=("is_active", "slug"), name="clinic_active_slug_idx"),
            models.Index(fields=("is_demo",), name="clinic_demo_idx"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist the clinic while preventing changes to its stable slug."""
        if not self._state.adding:
            persisted_slug = (
                Clinic.infrastructure_objects.only("slug").get(pk=self.pk).slug
            )
            if self.slug != persisted_slug:
                raise ValidationError(
                    {"slug": "O slug da clínica não pode ser alterado."}
                )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the clinic's user-facing name."""
        return self.name


class ClinicConfigurationQuerySet(models.QuerySet["ClinicConfiguration"]):
    """Tenant-scoped configuration queries."""

    def for_clinic(self, clinic_id: UUID) -> ClinicConfigurationQuerySet:
        return self.filter(clinic_id=clinic_id)


class ClinicConfigurationManager(models.Manager["ClinicConfiguration"]):
    """Default manager requiring an explicit clinic scope."""

    def get_queryset(self) -> NoReturn:
        raise TenantScopeRequiredError(
            "ClinicConfiguration queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ClinicConfigurationQuerySet:
        return ClinicConfigurationQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureClinicConfigurationManager(models.Manager["ClinicConfiguration"]):
    """Unrestricted configuration access for trusted write services."""

    def get_queryset(self) -> ClinicConfigurationQuerySet:
        return ClinicConfigurationQuerySet(self.model, using=self._db)


class ClinicConfiguration(UUIDTimestampedModel):
    """Minimized institutional and operational configuration for one tenant."""

    clinic = models.OneToOneField(
        Clinic,
        on_delete=models.CASCADE,
        related_name="configuration",
    )
    legal_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=120)
    registration_identifier = models.CharField(max_length=64, blank=True)
    administrative_email = models.EmailField()
    administrative_phone = models.CharField(max_length=32, blank=True)
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120)
    region = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=32)
    country_code = models.CharField(max_length=2)
    timezone_name = models.CharField(max_length=64, default="America/Sao_Paulo")
    language_code = models.CharField(max_length=10, default="pt-BR")
    service_channels = models.JSONField(default=list, blank=True)
    weekly_hours = models.JSONField(default=dict, blank=True)
    out_of_hours_instructions = models.TextField(blank=True, max_length=1000)
    logo = models.FileField(upload_to=clinic_logo_upload_to, blank=True)
    primary_color = models.CharField(max_length=7, default="#1D4ED8")
    secondary_color = models.CharField(max_length=7, default="#93C5FD")
    icon = models.CharField(max_length=500, blank=True)
    typography = models.CharField(max_length=64, blank=True)
    legal_text = models.TextField(max_length=5000, blank=True)
    sender_name = models.CharField(max_length=120, blank=True)
    sender_email = models.EmailField(blank=True)
    institutional_links = models.JSONField(default=list, blank=True)
    enabled_modules = models.JSONField(default=list, blank=True)
    modules_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinic_module_configuration_updates",
    )
    modules_updated_at = models.DateTimeField(null=True, blank=True)

    objects = ClinicConfigurationManager()
    infrastructure_objects = InfrastructureClinicConfigurationManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"

    def __str__(self) -> str:
        return self.display_name


class ClinicMembershipQuerySet(models.QuerySet["ClinicMembership"]):
    """Composable membership queries that retain explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> ClinicMembershipQuerySet:
        """Restrict membership access to one explicit clinic."""
        return self.filter(clinic_id=clinic_id)

    def active_on(self, on_date: date) -> ClinicMembershipQuerySet:
        """Restrict memberships to those valid and active on a date."""
        return self.filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=on_date),
            is_active=True,
            valid_from__lte=on_date,
        )


class ClinicMembershipManager(models.Manager["ClinicMembership"]):
    """Tenant-safe default manager requiring an explicit clinic ID."""

    def get_queryset(self) -> NoReturn:
        """Reject an unscoped membership query."""
        raise TenantScopeRequiredError(
            "ClinicMembership queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ClinicMembershipQuerySet:
        """Retain reverse-relation filters while adding explicit clinic scope."""
        queryset = ClinicMembershipQuerySet(self.model, using=self._db)
        core_filters = cast(
            dict[str, object],
            getattr(self, "core_filters", {}),
        )
        return queryset.filter(**core_filters).for_clinic(clinic_id)


class InfrastructureClinicMembershipManager(models.Manager["ClinicMembership"]):
    """Unrestricted membership access for middleware and administration only."""

    def get_queryset(self) -> ClinicMembershipQuerySet:
        """Return the unrestricted infrastructure queryset."""
        return ClinicMembershipQuerySet(self.model, using=self._db)


class ClinicMembership(UUIDTimestampedModel):
    """A user's dated authorization relationship with one clinic."""

    class Role(models.TextChoices):
        """Stable authorization roles supported by current persistence."""

        CLINIC_ADMIN = "clinic_admin", "Administrador da clínica"
        THERAPIST = "therapist", "Terapeuta"
        ADMINISTRATIVE_STAFF = "administrative_staff", "Equipe administrativa"
        PATIENT = "patient", "Paciente"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="clinic_memberships",
    )
    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=64, choices=Role)
    unit_name = models.CharField(max_length=120, blank=True)
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="authorized_clinic_memberships",
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)

    objects = ClinicMembershipManager()
    infrastructure_objects = InfrastructureClinicMembershipManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "clinic"),
                name="unique_user_clinic_membership",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="membership_valid_until_on_or_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "user", "is_active"),
                name="membership_clinic_user_idx",
            ),
            models.Index(
                fields=("user", "is_active", "valid_from", "valid_until"),
                name="membership_user_validity_idx",
            ),
            models.Index(
                fields=("clinic", "role", "is_active", "valid_from", "valid_until"),
                name="membership_prof_list_idx",
            ),
        ]

    def professional_status(self, *, on_date: date) -> str:
        """Return a factual professional membership state for one effective date."""
        if not self.is_active:
            return "suspended"
        if self.valid_from > on_date:
            return "scheduled"
        if self.valid_until is not None and self.valid_until < on_date:
            return "expired"
        return "active"

    def __str__(self) -> str:
        """Return a stable technical membership representation."""
        return f"{self.user_id}:{self.clinic_id}:{self.role}"


from .whitelabel_models import (  # noqa: E402
    BrandThemeVersion,
    BrandThemeVersionManager,
    BrandThemeVersionQuerySet,
    CommunicationTemplate,
    CommunicationTemplateManager,
    CommunicationTemplateQuerySet,
    CustomDomain,
    CustomDomainManager,
    CustomDomainQuerySet,
    InfrastructureBrandThemeVersionManager,
    InfrastructureCommunicationTemplateManager,
    InfrastructureCustomDomainManager,
)

__all__ = [
    "BrandThemeVersion",
    "BrandThemeVersionManager",
    "BrandThemeVersionQuerySet",
    "Clinic",
    "ClinicConfiguration",
    "ClinicConfigurationManager",
    "ClinicConfigurationQuerySet",
    "ClinicManager",
    "ClinicMembership",
    "ClinicMembershipManager",
    "ClinicMembershipQuerySet",
    "ClinicQuerySet",
    "CommunicationTemplate",
    "CommunicationTemplateManager",
    "CommunicationTemplateQuerySet",
    "CustomDomain",
    "CustomDomainManager",
    "CustomDomainQuerySet",
    "InfrastructureBrandThemeVersionManager",
    "InfrastructureClinicConfigurationManager",
    "InfrastructureClinicManager",
    "InfrastructureClinicMembershipManager",
    "InfrastructureCommunicationTemplateManager",
    "InfrastructureCustomDomainManager",
    "TenantScopeRequiredError",
    "clinic_logo_upload_to",
]
