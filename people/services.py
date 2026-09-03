"""Public service interface for the people domain."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.services import IssuedInvitation, User, issue_invitation
from clinics.selectors import active_membership_roles_for_users
from clinics.services import authorized_active_clinic, lock_clinic_for_update
from core.services import PrivateUploadPolicy, require_clean_malware_scan
from core.services import Service as Service

from .events import (
    care_relationship_changed,
    patient_profile_updated,
    professional_credential_audit_required,
    professional_credential_revoked,
    professional_profile_updated,
)
from .models import (
    CareRelationship,
    PatientInvitationLink,
    PatientProfile,
    ProfessionalCredential,
    ProfessionalProfile,
)

__all__ = [
    "CareRelationshipSuspension",
    "ProfessionalCredential",
    "ProfessionalProfile",
    "Service",
    "close_patient_care_relationship",
    "create_patient_care_relationship",
    "invitation_expiration_after",
    "issue_patient_invitation",
    "register_patient_profile",
    "suspend_expired_care_relationships",
    "suspend_inconsistent_care_relationships",
    "transfer_patient_care_relationship",
    "update_professional_profile",
    "update_patient_profile_contact",
    "verify_professional_credential",
    "revoke_professional_credential",
]


@transaction.atomic
def verify_professional_credential(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    profile_id: UUID,
    council_name: str,
    council_number: str,
    council_jurisdiction: str,
    request_id: UUID,
) -> ProfessionalCredential:
    """Record a clinic-verified professional credential (audited governance)."""
    _require_clinic_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    profile = ProfessionalProfile.infrastructure_objects.filter(
        pk=profile_id, clinic_id=clinic_id
    ).first()
    if profile is None:
        raise PermissionDenied
    credential, _ = ProfessionalCredential.objects.get_or_create(profile=profile)
    credential.council_name = council_name.strip()
    credential.council_number = council_number.strip()
    credential.council_jurisdiction = council_jurisdiction.strip()
    credential.status = ProfessionalCredential.Status.VERIFIED
    credential.save(
        update_fields=(
            "council_name",
            "council_number",
            "council_jurisdiction",
            "status",
            "updated_at",
        )
    )
    professional_credential_audit_required.send(
        sender=ProfessionalCredential,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="professional_credential",
        resource_id=str(credential.pk),
        request_id=request_id,
    )
    return credential


@transaction.atomic
def revoke_professional_credential(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    profile_id: UUID,
    reason: str,
    request_id: UUID,
) -> ProfessionalCredential:
    """Revoke one professional credential with a required audited reason."""
    _require_clinic_admin(clinic_id=clinic_id, actor=actor)
    lock_clinic_for_update(clinic_id=clinic_id)
    profile = ProfessionalProfile.infrastructure_objects.filter(
        pk=profile_id, clinic_id=clinic_id
    ).first()
    if profile is None:
        raise PermissionDenied
    credential: ProfessionalCredential | None = ProfessionalCredential.objects.filter(
        profile=profile
    ).first()
    if credential is None:
        raise PermissionDenied
    if credential.status == ProfessionalCredential.Status.REVOKED:
        raise ValidationError("Esta credencial já está revogada.")
    if not reason.strip():
        raise ValidationError("Informe o motivo da revogação.")
    credential.status = ProfessionalCredential.Status.REVOKED
    credential.save(update_fields=("status", "updated_at"))
    professional_credential_revoked.send(
        sender=ProfessionalCredential,
        clinic_id=clinic_id,
        professional_user_id=profile.user_id,
        reason=reason.strip(),
        request_id=request_id,
    )
    professional_credential_audit_required.send(
        sender=ProfessionalCredential,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        action="update",
        resource_type="professional_credential",
        resource_id=str(credential.pk),
        request_id=request_id,
    )
    return credential


def _require_clinic_admin(*, clinic_id: UUID, actor: AbstractBaseUser) -> None:
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")


@transaction.atomic
def update_professional_profile(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    user_id: UUID,
    full_name: str,
    social_name: str,
    professional_email: str,
    professional_phone: str,
    photo: UploadedFile | None,
    biography: str,
    accessibility_preferences: str,
    category: str,
    specialties: list[str],
    council_name: str,
    council_number: str,
    council_jurisdiction: str,
    request_id: UUID,
) -> ProfessionalProfile:
    """Create or update one tenant-owned professional profile and declaration."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="professionals.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    roles = active_membership_roles_for_users(
        clinic_id=clinic_id,
        user_ids={user_id},
        on_date=date.today(),
    )
    if roles.get(user_id) != "therapist":
        raise PermissionDenied

    normalized_name = full_name.strip()
    normalized_email = professional_email.strip().lower()
    if not normalized_name or not normalized_email:
        raise ValidationError("Informe nome e e-mail profissional.")
    if category not in ProfessionalProfile.Category.values:
        raise ValidationError("Selecione uma categoria profissional válida.")
    normalized_specialties = sorted(
        {item.strip().lower() for item in specialties if item.strip()}
    )
    if len(normalized_specialties) != len(specialties) or any(
        re.fullmatch(r"[a-z][a-z0-9_]{1,63}", item) is None
        for item in normalized_specialties
    ):
        raise ValidationError(
            "Informe especialidades técnicas válidas e sem repetição."
        )

    credential_parts = tuple(
        value.strip() for value in (council_name, council_number, council_jurisdiction)
    )
    if any(credential_parts) and not all(credential_parts):
        raise ValidationError("Informe conselho, número e jurisdição em conjunto.")

    profile, _created = (
        ProfessionalProfile.infrastructure_objects.select_for_update().get_or_create(
            clinic_id=clinic_id,
            user_id=user_id,
            defaults={
                "full_name": normalized_name,
                "professional_email": normalized_email,
                "category": category,
            },
        )
    )
    profile.full_name = normalized_name
    profile.social_name = social_name.strip()
    profile.professional_email = normalized_email
    profile.professional_phone = professional_phone.strip()
    profile.biography = biography.strip()
    profile.accessibility_preferences = accessibility_preferences.strip()
    profile.category = category
    profile.specialties = normalized_specialties
    if photo is not None:
        if (photo.size or 0) > 2 * 1024 * 1024:
            raise ValidationError("A foto excede o limite de 2 MB.")
        metadata = PrivateUploadPolicy().validate(photo)
        if metadata.detected_media_type not in {"image/png", "image/jpeg"}:
            raise ValidationError("A foto deve ser PNG ou JPEG.")
        require_clean_malware_scan(photo)
        photo.seek(0)
        profile.photo.save(metadata.safe_name, photo, save=False)
    profile.full_clean(validate_unique=False, validate_constraints=False)
    profile.save()

    credential, _created = ProfessionalCredential.objects.get_or_create(profile=profile)
    (
        credential.council_name,
        credential.council_number,
        credential.council_jurisdiction,
    ) = credential_parts
    credential.status = ProfessionalCredential.Status.DECLARED
    credential.full_clean(validate_unique=False)
    credential.save()
    professional_profile_updated.send(
        sender=ProfessionalProfile,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(profile.pk),
        request_id=request_id,
    )
    return profile


def _normalized_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"+{digits}" if digits else ""


@transaction.atomic
def register_patient_profile(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    full_name: str,
    social_name: str,
    birth_date: date,
    gender: str,
    email: str,
    phone: str,
    language_code: str,
    timezone_name: str,
    accessibility_preferences: str,
    address: dict[str, object],
    address_purpose: str,
    emergency_contact: dict[str, object],
    emergency_contact_purpose: str,
    request_id: UUID,
) -> PatientProfile:
    """Create one minimized patient profile under an authorized tenant."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="patients.create",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized_name = full_name.strip()
    normalized_email = email.strip().lower()
    normalized_phone = _normalized_phone(phone)
    if not normalized_name or not normalized_email:
        raise ValidationError("Informe nome e e-mail da pessoa paciente.")
    if gender and gender not in PatientProfile.Gender.values:
        raise ValidationError("Selecione uma opção de gênero válida.")
    if address and not address_purpose.strip():
        raise ValidationError("Informe a finalidade para registrar o endereço.")
    if emergency_contact and not emergency_contact_purpose.strip():
        raise ValidationError("Informe a finalidade para o contato de emergência.")
    duplicate_filter = Q(email=normalized_email)
    if normalized_phone:
        duplicate_filter |= Q(phone=normalized_phone)
    if PatientProfile.infrastructure_objects.filter(
        duplicate_filter,
        clinic_id=clinic_id,
    ).exists():
        raise ValidationError("Foi encontrada uma possível duplicidade nesta clínica.")

    profile = PatientProfile(
        clinic_id=clinic_id,
        full_name=normalized_name,
        social_name=social_name.strip(),
        birth_date=birth_date,
        gender=gender,
        email=normalized_email,
        phone=normalized_phone,
        language_code=language_code.strip() or "pt-BR",
        timezone_name=timezone_name.strip() or "America/Sao_Paulo",
        accessibility_preferences=accessibility_preferences.strip(),
        address=address,
        address_purpose=address_purpose.strip(),
        emergency_contact=emergency_contact,
        emergency_contact_purpose=emergency_contact_purpose.strip(),
    )
    profile.full_clean(validate_unique=False, validate_constraints=False)
    profile.save(force_insert=True)
    patient_profile_updated.send(
        sender=PatientProfile,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(profile.pk),
        request_id=request_id,
    )
    return profile


@transaction.atomic
def update_patient_profile_contact(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    phone: str,
    request_id: UUID,
) -> PatientProfile:
    """Update one contact only after tenant and actor authorization."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="patients.create",
    )
    profile = (
        PatientProfile.infrastructure_objects.select_for_update()
        .filter(pk=patient_profile_id, clinic_id=clinic_id)
        .first()
    )
    if profile is None:
        raise PermissionDenied
    profile.phone = _normalized_phone(phone)
    profile.save(update_fields=("phone", "updated_at"))
    patient_profile_updated.send(
        sender=PatientProfile,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(profile.pk),
        request_id=request_id,
    )
    return profile


def invitation_expiration_after(*, days: int) -> datetime:
    """Build an aware invitation expiration without exposing clock handling to views."""
    if days < 1 or days > 30:
        raise ValueError("days must be between 1 and 30")
    return timezone.now() + timedelta(days=days)


@transaction.atomic
def issue_patient_invitation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    expires_at: datetime,
    request_id: UUID,
) -> IssuedInvitation:
    """Issue a one-time invitation tied to a server-owned patient profile."""
    del request_id
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="invitation.issue",
    )
    profile = (
        PatientProfile.infrastructure_objects.select_for_update()
        .filter(pk=patient_profile_id, clinic_id=clinic_id, user__isnull=True)
        .first()
    )
    if profile is None:
        raise PermissionDenied
    if not isinstance(actor, User):
        raise PermissionDenied
    issued = issue_invitation(
        clinic_id=clinic_id,
        issuer=actor,
        recipient_email=profile.email,
        initial_role="patient",
        expires_at=expires_at,
    )
    PatientInvitationLink.objects.update_or_create(
        patient_profile=profile,
        defaults={"invitation": issued.invitation},
    )
    return issued


@transaction.atomic
def create_patient_care_relationship(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    therapist_id: UUID,
    patient_profile_id: UUID,
    function: str,
    valid_from: date,
    valid_until: date | None,
    request_id: UUID,
) -> CareRelationship:
    """Create an explicit, dated professional-patient authorization link."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="care_relationship.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    roles = active_membership_roles_for_users(
        clinic_id=clinic_id,
        user_ids={therapist_id},
        on_date=date.today(),
    )
    if roles.get(therapist_id) != "therapist":
        raise PermissionDenied
    profile = (
        PatientProfile.infrastructure_objects.select_for_update()
        .filter(pk=patient_profile_id, clinic_id=clinic_id)
        .first()
    )
    if profile is None:
        raise PermissionDenied
    if not function.strip():
        raise ValidationError("Informe a função do profissional no vínculo.")
    relationship = CareRelationship(
        clinic_id=clinic_id,
        therapist_id=therapist_id,
        patient_id=profile.user_id,
        patient_profile=profile,
        function=function.strip(),
        authorized_by_id=actor.pk,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
    )
    relationship.full_clean(validate_unique=False, validate_constraints=False)
    relationship.save(force_insert=True)
    care_relationship_changed.send(
        sender=CareRelationship,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(relationship.pk),
        request_id=request_id,
    )
    return relationship


@transaction.atomic
def close_patient_care_relationship(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    relationship_id: UUID,
    ended_on: date,
    request_id: UUID,
) -> CareRelationship:
    """Close one scoped care relationship while preserving its history."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="care_relationship.manage",
    )
    relationship = (
        CareRelationship.infrastructure_objects.select_for_update()
        .filter(pk=relationship_id, clinic_id=clinic_id)
        .first()
    )
    if relationship is None:
        raise PermissionDenied
    if ended_on < relationship.valid_from:
        raise ValidationError("A data de encerramento não pode preceder o início.")
    relationship.valid_until = ended_on
    relationship.is_active = False
    relationship.save(update_fields=("valid_until", "is_active", "updated_at"))
    care_relationship_changed.send(
        sender=CareRelationship,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(relationship.pk),
        request_id=request_id,
    )
    return relationship


@transaction.atomic
def transfer_patient_care_relationship(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    relationship_id: UUID,
    new_therapist_id: UUID,
    transferred_on: date,
    request_id: UUID,
) -> CareRelationship:
    """Reassign one active care link to a different authorized therapist."""
    authorized_active_clinic(
        clinic_id=clinic_id,
        actor=actor,
        action="care_relationship.manage",
    )
    lock_clinic_for_update(clinic_id=clinic_id)
    relationship = (
        CareRelationship.infrastructure_objects.select_for_update()
        .filter(pk=relationship_id, clinic_id=clinic_id, is_active=True)
        .first()
    )
    if relationship is None:
        raise PermissionDenied
    if relationship.therapist_id == new_therapist_id:
        raise ValidationError("O novo profissional deve ser diferente do atual.")
    if transferred_on < relationship.valid_from:
        raise ValidationError("A data de transferência não pode preceder o início.")
    original_valid_until = relationship.valid_until
    if original_valid_until is not None and transferred_on > original_valid_until:
        raise ValidationError("A data de transferência excede o término do vínculo.")
    roles = active_membership_roles_for_users(
        clinic_id=clinic_id,
        user_ids={new_therapist_id},
        on_date=transferred_on,
    )
    if roles.get(new_therapist_id) != "therapist":
        raise PermissionDenied

    relationship.is_active = False
    relationship.valid_until = transferred_on
    relationship.save(update_fields=("is_active", "valid_until", "updated_at"))
    care_relationship_changed.send(
        sender=CareRelationship,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(relationship.pk),
        request_id=request_id,
    )

    transferred = CareRelationship(
        clinic_id=clinic_id,
        therapist_id=new_therapist_id,
        patient_id=relationship.patient_id,
        patient_profile_id=relationship.patient_profile_id,
        function=relationship.function,
        authorized_by_id=actor.pk,
        is_active=True,
        valid_from=transferred_on,
        valid_until=original_valid_until,
    )
    transferred.full_clean(validate_unique=False, validate_constraints=False)
    transferred.save(force_insert=True)
    care_relationship_changed.send(
        sender=CareRelationship,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(transferred.pk),
        request_id=request_id,
    )
    return transferred


@dataclass(frozen=True, slots=True)
class CareRelationshipSuspension:
    """Minimized result from validating one professional-patient link."""

    resource_id: UUID
    reason: str


def suspend_expired_care_relationships(
    *, clinic_id: UUID, on_date: date
) -> tuple[UUID, ...]:
    """Suspend expired care links inside a caller-owned transaction."""
    relationships = list(
        CareRelationship.infrastructure_objects.select_for_update().filter(
            clinic_id=clinic_id,
            is_active=True,
            valid_until__lt=on_date,
        )
    )
    for relationship in relationships:
        relationship.is_active = False
        relationship.save(update_fields=("is_active", "updated_at"))
    return tuple(relationship.pk for relationship in relationships)


def suspend_inconsistent_care_relationships(
    *, clinic_id: UUID, on_date: date
) -> tuple[CareRelationshipSuspension, ...]:
    """Suspend expired links and links whose current party roles are inconsistent."""
    relationships = list(
        CareRelationship.infrastructure_objects.select_for_update().filter(
            clinic_id=clinic_id,
            is_active=True,
        )
    )
    party_ids = {
        party_id
        for relationship in relationships
        for party_id in (relationship.therapist_id, relationship.patient_id)
        if party_id is not None
    }
    roles = active_membership_roles_for_users(
        clinic_id=clinic_id,
        user_ids=party_ids,
        on_date=on_date,
    )
    suspensions: list[CareRelationshipSuspension] = []
    for relationship in relationships:
        reason = ""
        if relationship.valid_until is not None and relationship.valid_until < on_date:
            reason = "care_relationship_expired"
        elif relationship.therapist_id not in roles:
            reason = "therapist_membership_inactive"
        elif roles[relationship.therapist_id] != "therapist":
            reason = "therapist_membership_not_therapist"
        elif (
            relationship.patient_id is None
            or roles.get(relationship.patient_id) != "patient"
        ):
            reason = "patient_membership_inactive"
        if not reason:
            continue
        relationship.is_active = False
        relationship.save(update_fields=("is_active", "updated_at"))
        suspensions.append(
            CareRelationshipSuspension(
                resource_id=relationship.pk,
                reason=reason,
            )
        )
    return tuple(suspensions)
