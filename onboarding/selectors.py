"""Read selectors for onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from clinics.selectors import (
    clinic_setup_complete,
    has_clinic_admin_membership,
    has_non_patient_memberships,
)
from consents.selectors import has_published_documents
from core.selectors import Selector as Selector
from people.selectors import has_patient_profiles

from .models import PatientOnboarding

__all__ = [
    "ClinicOnboardingChecklistItem",
    "Selector",
    "clinic_onboarding_checklist",
    "patient_onboarding_snapshot",
]


@dataclass(frozen=True, slots=True)
class ClinicOnboardingChecklistItem:
    """One factual readiness item for the clinic onboarding checklist."""

    key: str
    label: str
    is_complete: bool
    detail: str


def clinic_onboarding_checklist(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> tuple[ClinicOnboardingChecklistItem, ...]:
    """Return factual readiness items for one active clinic administrator."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    return (
        ClinicOnboardingChecklistItem(
            key="clinic_profile",
            label="Perfil da clínica completo",
            is_complete=clinic_setup_complete(clinic_id=clinic_id),
            detail="Identidade, operação, identidade visual e módulos configurados.",
        ),
        ClinicOnboardingChecklistItem(
            key="professionals_invited",
            label="Profissionais convidados",
            is_complete=has_non_patient_memberships(clinic_id=clinic_id),
            detail="Pelo menos um profissional ou membro administrativo associado.",
        ),
        ClinicOnboardingChecklistItem(
            key="terms_published",
            label="Termos publicados",
            is_complete=has_published_documents(clinic_id=clinic_id),
            detail="Documentos de consentimento publicados e vigentes.",
        ),
        ClinicOnboardingChecklistItem(
            key="permissions_configured",
            label="Permissões configuradas",
            is_complete=has_clinic_admin_membership(clinic_id=clinic_id),
            detail="Administrador da clínica definido.",
        ),
        ClinicOnboardingChecklistItem(
            key="first_patient",
            label="Primeiro paciente",
            is_complete=has_patient_profiles(clinic_id=clinic_id),
            detail="Pelo menos um paciente cadastrado ou convidado.",
        ),
    )


def patient_onboarding_snapshot(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> PatientOnboarding | None:
    """Return one patient's current onboarding state, if any."""
    return PatientOnboarding.infrastructure_objects.filter(
        clinic_id=clinic_id, patient_profile_id=patient_profile_id
    ).first()
