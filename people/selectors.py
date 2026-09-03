"""Authorized patient and professional selectors."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Q
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from clinics.selectors import (
    active_clinics_for_actor,
    active_member_identity_for_role,
    memberships_visible_to,
)
from core.selectors import Selector as Selector

from .models import CareRelationship, PatientProfile, ProfessionalProfile
from .policies import PatientAuthorizationPolicy


@dataclass(frozen=True, slots=True)
class ProfessionalDirectoryRow:
    membership_id: UUID
    user_id: UUID
    full_name: str
    social_name: str
    role: str
    status: str
    unit_name: str
    category: str
    specialties: tuple[str, ...]


def professional_directory_visible_to(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    status: str = "",
    role: str = "",
    specialty: str = "",
    on_date: date,
) -> tuple[ProfessionalDirectoryRow, ...]:
    """Return minimized professional rows through an authorized tenant scope."""
    clinic = next(
        (
            candidate
            for candidate in active_clinics_for_actor(actor)
            if candidate.pk == clinic_id
        ),
        None,
    )
    if clinic is None:
        return ()
    memberships = memberships_visible_to(actor, clinic).exclude(role="patient")
    if role:
        memberships = memberships.filter(role=role)
    membership_rows = list(memberships.order_by("user_id"))
    profiles = {
        profile.user_id: profile
        for profile in ProfessionalProfile.objects.for_clinic(clinic_id).filter(
            user_id__in=[membership.user_id for membership in membership_rows]
        )
    }
    rows: list[ProfessionalDirectoryRow] = []
    for membership in membership_rows:
        effective_status = membership.professional_status(on_date=on_date)
        if status and effective_status != status:
            continue
        profile = profiles.get(membership.user_id)
        profile_specialties = tuple(profile.specialties) if profile is not None else ()
        if specialty and specialty not in profile_specialties:
            continue
        rows.append(
            ProfessionalDirectoryRow(
                membership_id=membership.pk,
                user_id=membership.user_id,
                full_name=profile.full_name
                if profile is not None
                else "Perfil pendente",
                social_name=profile.social_name if profile is not None else "",
                role=membership.role,
                status=effective_status,
                unit_name=membership.unit_name,
                category=profile.category if profile is not None else "",
                specialties=profile_specialties,
            )
        )
    return tuple(rows)


def patient_visible_to(
    *,
    actor: AbstractBaseUser,
    clinic: Any,
    patient_id: UUID,
    action: str,
) -> AbstractBaseUser | None:
    """Resolve only a same-tenant patient authorized for the requested action."""
    patient = active_member_identity_for_role(
        clinic_id=clinic.pk,
        user_id=patient_id,
        role="patient",
    )
    if patient is None:
        return None
    if not PatientAuthorizationPolicy().is_allowed(
        actor=actor,
        clinic=clinic,
        patient=patient,
        action=action,
        record_is_active=True,
    ):
        return None
    return patient


def has_patient_profiles(*, clinic_id: UUID) -> bool:
    """Return whether at least one patient profile exists in the clinic."""
    return PatientProfile.objects.for_clinic(clinic_id).exists()


def patient_profiles_for_clinic(*, clinic_id: UUID) -> list[PatientProfile]:
    """Return all patient profiles for a clinic ordered by full_name."""
    return list(PatientProfile.objects.for_clinic(clinic_id).order_by("full_name"))


def active_patient_profile_count(*, clinic_id: UUID, on_date: date) -> int:
    """Return distinct patient profiles with an active care relationship."""
    return (
        CareRelationship.objects.for_clinic(clinic_id)
        .active_on(on_date)
        .values("patient_profile_id")
        .distinct()
        .count()
    )


def patient_profile_for_user(
    *, clinic_id: UUID, user_id: UUID
) -> PatientProfile | None:
    """Return the patient profile linked to one identity inside a clinic."""
    return PatientProfile.objects.for_clinic(clinic_id).filter(user_id=user_id).first()


@dataclass(frozen=True, slots=True)
class LinkedPatientRow:
    """Minimized patient facts for one therapist's care links."""

    patient_profile_id: UUID
    user_id: UUID | None
    full_name: str
    social_name: str
    email: str
    phone: str
    link_valid_from: date
    link_is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LinkedTherapistRow:
    """Minimized professional facts for one patient's care links."""

    therapist_id: UUID
    full_name: str
    social_name: str


def linked_therapists_for_patient(
    *, clinic_id: UUID, patient_user_id: UUID, on_date: date
) -> tuple[LinkedTherapistRow, ...]:
    """Return minimized active therapist rows linked to one patient identity."""
    relationships = (
        CareRelationship.objects.for_clinic(clinic_id)
        .filter(
            patient_profile__user_id=patient_user_id,
            is_active=True,
            valid_from__lte=on_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
    )
    therapist_ids = {relationship.therapist_id for relationship in relationships}
    if not therapist_ids:
        return ()
    profiles = {
        profile.user_id: profile
        for profile in ProfessionalProfile.objects.for_clinic(clinic_id).filter(
            user_id__in=therapist_ids
        )
    }
    rows = [
        LinkedTherapistRow(
            therapist_id=therapist_id,
            full_name=(
                profiles[therapist_id].full_name
                if therapist_id in profiles
                else "Profissional"
            ),
            social_name=(
                profiles[therapist_id].social_name if therapist_id in profiles else ""
            ),
        )
        for therapist_id in therapist_ids
    ]
    return tuple(sorted(rows, key=lambda row: row.full_name))


def linked_patients_for_therapist(
    *, clinic_id: UUID, therapist_id: UUID, on_date: date
) -> tuple[LinkedPatientRow, ...]:
    """Return minimized active patient rows for one therapist's care links."""
    relationships = (
        CareRelationship.objects.for_clinic(clinic_id)
        .filter(
            therapist_id=therapist_id,
            is_active=True,
            valid_from__lte=on_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .select_related("patient_profile")
        .order_by("patient_profile__full_name", "patient_profile_id")
    )
    rows: list[LinkedPatientRow] = []
    for relationship in relationships:
        profile = relationship.patient_profile
        if profile is None:
            continue
        rows.append(
            LinkedPatientRow(
                patient_profile_id=profile.pk,
                user_id=profile.user_id,
                full_name=profile.full_name,
                social_name=profile.social_name,
                email=profile.email,
                phone=profile.phone,
                link_valid_from=relationship.valid_from,
                link_is_active=relationship.is_active,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
        )
    return tuple(rows)


def patient_profile_detail_for_actor(
    *, clinic_id: UUID, actor: AbstractBaseUser, patient_profile_id: UUID
) -> PatientProfile | None:
    """Return one patient profile when the actor may open its record."""
    profile = (
        PatientProfile.objects.for_clinic(clinic_id)
        .filter(pk=patient_profile_id)
        .first()
    )
    if profile is None:
        return None
    today = timezone.localdate()
    if has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=today,
    ) or has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="administrative_staff",
        on_date=today,
    ):
        return profile
    if (
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=today
        )
        and CareRelationship.objects.for_clinic(clinic_id)
        .active_on(today)
        .filter(therapist_id=actor.pk, patient_profile_id=patient_profile_id)
        .exists()
    ):
        return profile
    return None


__all__ = [
    "LinkedPatientRow",
    "LinkedTherapistRow",
    "ProfessionalDirectoryRow",
    "Selector",
    "active_patient_profile_count",
    "has_patient_profiles",
    "linked_patients_for_therapist",
    "linked_therapists_for_patient",
    "patient_profile_detail_for_actor",
    "patient_profile_for_user",
    "patient_profiles_for_clinic",
    "patient_visible_to",
    "professional_directory_visible_to",
]
