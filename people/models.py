"""Patient and care-relationship persistence models."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.persistence import UUIDTimestampedModel


def professional_photo_upload_to(instance: ProfessionalProfile, filename: str) -> str:
    """Build an opaque tenant-owned path without retaining the supplied filename."""
    suffix = Path(filename).suffix.lower()
    clinic_id = cast(Any, instance).clinic_id
    return f"professionals/{clinic_id}/{uuid4().hex}{suffix}"


class ProfessionalProfileQuerySet(models.QuerySet["ProfessionalProfile"]):
    """Professional profiles that always retain explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> ProfessionalProfileQuerySet:
        return self.filter(clinic_id=clinic_id)


class ProfessionalProfileManager(models.Manager["ProfessionalProfile"]):
    """Refuse accidental global enumeration of professional profiles."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "ProfessionalProfile queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> ProfessionalProfileQuerySet:
        return ProfessionalProfileQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureProfessionalProfileManager(models.Manager["ProfessionalProfile"]):
    """Unrestricted profile access reserved for transactional services."""

    def get_queryset(self) -> ProfessionalProfileQuerySet:
        return ProfessionalProfileQuerySet(self.model, using=self._db)


class ProfessionalProfile(UUIDTimestampedModel):
    """Tenant-owned public professional presentation separated from login identity."""

    class Category(models.TextChoices):
        PSYCHOLOGIST = "psychologist", "Psicologia"
        THERAPIST = "therapist", "Terapia"
        OTHER = "other", "Outra categoria"

    clinic = models.ForeignKey(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="professional_profiles"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="professional_profiles",
    )
    full_name = models.CharField(max_length=255)
    social_name = models.CharField(max_length=255, blank=True)
    professional_email = models.EmailField()
    professional_phone = models.CharField(max_length=32, blank=True)
    photo = models.FileField(upload_to=professional_photo_upload_to, blank=True)
    biography = models.TextField(max_length=2000, blank=True)
    accessibility_preferences = models.TextField(max_length=1000, blank=True)
    category = models.CharField(max_length=32, choices=Category)
    specialties = models.JSONField(default=list, blank=True)

    objects = ProfessionalProfileManager()
    infrastructure_objects = InfrastructureProfessionalProfileManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "user"), name="unique_professional_profile_per_clinic"
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "category", "full_name"),
                name="prof_clinic_category_idx",
            )
        ]

    @property
    def council_name(self) -> str:
        return self.credential.council_name

    @property
    def council_number(self) -> str:
        return self.credential.council_number

    @property
    def council_jurisdiction(self) -> str:
        return self.credential.council_jurisdiction

    @property
    def credential_status(self) -> str:
        return self.credential.status

    def get_credential_status_display(self) -> str:
        return str(self.credential.get_status_display())


class ProfessionalCredential(UUIDTimestampedModel):
    """A declared credential kept distinct from presentation and authentication."""

    class Status(models.TextChoices):
        DECLARED = "declared", "Informado pelo profissional"
        VERIFIED = "verified", "Verificado pela clínica"
        REVOKED = "revoked", "Revogado"

    profile = models.OneToOneField(
        ProfessionalProfile,
        on_delete=models.CASCADE,
        related_name="credential",
    )
    council_name = models.CharField(max_length=64, blank=True)
    council_number = models.CharField(max_length=64, blank=True)
    council_jurisdiction = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DECLARED)


class PatientProfileQuerySet(models.QuerySet["PatientProfile"]):
    """Patient profiles retaining explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> PatientProfileQuerySet:
        return self.filter(clinic_id=clinic_id)


class PatientProfileManager(models.Manager["PatientProfile"]):
    """Refuse accidental global access to patient profiles."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("PatientProfile queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> PatientProfileQuerySet:
        return PatientProfileQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructurePatientProfileManager(models.Manager["PatientProfile"]):
    """Unrestricted patient access reserved for controlled services."""

    def get_queryset(self) -> PatientProfileQuerySet:
        return PatientProfileQuerySet(self.model, using=self._db)


class PatientProfile(UUIDTimestampedModel):
    """Tenant-owned care identity kept separate from account credentials."""

    class Gender(models.TextChoices):
        WOMAN = "woman", "Mulher"
        MAN = "man", "Homem"
        NON_BINARY = "non_binary", "Pessoa não binária"
        OTHER = "other", "Outro"
        UNDISCLOSED = "undisclosed", "Prefiro não informar"

    clinic = models.ForeignKey(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="patient_profiles"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="patient_profiles",
    )
    full_name = models.CharField(max_length=255)
    social_name = models.CharField(max_length=255, blank=True)
    birth_date = models.DateField()
    gender = models.CharField(max_length=16, choices=Gender, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    language_code = models.CharField(max_length=16, default="pt-BR")
    timezone_name = models.CharField(max_length=64, default="America/Sao_Paulo")
    accessibility_preferences = models.TextField(max_length=1000, blank=True)
    address = models.JSONField(default=dict, blank=True)
    address_purpose = models.CharField(max_length=255, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    emergency_contact_purpose = models.CharField(max_length=255, blank=True)

    objects = PatientProfileManager()
    infrastructure_objects = InfrastructurePatientProfileManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "user"),
                condition=Q(user__isnull=False),
                name="unique_linked_patient_account_per_clinic",
            )
        ]
        indexes = [
            models.Index(fields=("clinic", "email"), name="patient_clinic_email_idx"),
            models.Index(fields=("clinic", "phone"), name="patient_clinic_phone_idx"),
        ]


class PatientInvitationLink(UUIDTimestampedModel):
    """Server-owned association from one invitation to an existing profile."""

    patient_profile = models.OneToOneField(
        PatientProfile,
        on_delete=models.CASCADE,
        related_name="invitation_link",
    )
    invitation = models.OneToOneField(
        "accounts.ClinicInvitation",
        on_delete=models.CASCADE,
        related_name="patient_profile_link",
    )


class CareRelationshipQuerySet(models.QuerySet["CareRelationship"]):
    """Composable patient relationships that retain explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> CareRelationshipQuerySet:
        return self.filter(clinic_id=clinic_id)

    def active_on(self, on_date: date) -> CareRelationshipQuerySet:
        return self.filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=on_date),
            is_active=True,
            valid_from__lte=on_date,
        )


class CareRelationshipManager(models.Manager["CareRelationship"]):
    """Require explicit clinic scope for application queries."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("CareRelationship queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> CareRelationshipQuerySet:
        return CareRelationshipQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureCareRelationshipManager(models.Manager["CareRelationship"]):
    """Unrestricted relationship access reserved for controlled infrastructure."""

    def get_queryset(self) -> CareRelationshipQuerySet:
        return CareRelationshipQuerySet(self.model, using=self._db)


class CareRelationship(UUIDTimestampedModel):
    """Dated authorization link between a therapist and patient in one clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="care_relationships",
    )
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="therapist_care_relationships",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="patient_care_relationships",
    )
    patient_profile = models.ForeignKey(
        PatientProfile,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="care_relationships",
    )
    function = models.CharField(max_length=64, default="primary_therapist")
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="authorized_care_relationships",
    )
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField()
    valid_until = models.DateField(blank=True, null=True)

    objects = CareRelationshipManager()
    infrastructure_objects = InfrastructureCareRelationshipManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "therapist", "patient", "valid_from"),
                name="unique_care_relationship_period_start",
            ),
            models.CheckConstraint(
                condition=~Q(therapist=models.F("patient")),
                name="care_relationship_distinct_people",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True)
                | Q(valid_until__gte=models.F("valid_from")),
                name="care_relationship_valid_dates",
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "therapist", "patient", "is_active"),
                name="care_clinic_people_active_idx",
            )
        ]
