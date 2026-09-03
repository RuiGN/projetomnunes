"""Authorization policies for patient-owned resources."""

from typing import Any

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from clinics.policies import ClinicAuthorizationPolicy, has_active_clinic_role
from core.policies import AuthorizationPolicy as AuthorizationPolicy

from .models import CareRelationship


class PatientAuthorizationPolicy:
    """Authorize a patient resource by tenant, role, link and record state."""

    def is_allowed(
        self,
        *,
        actor: AbstractBaseUser,
        clinic: Any,
        patient: AbstractBaseUser,
        action: str,
        record_is_active: bool,
    ) -> bool:
        """Return a deny-by-default resource decision from persisted state."""
        if not record_is_active or not ClinicAuthorizationPolicy().is_allowed(
            actor, clinic, action
        ):
            return False

        on_date = timezone.localdate()
        if not has_active_clinic_role(
            clinic_id=clinic.pk,
            user_id=patient.pk,
            role="patient",
            on_date=on_date,
        ):
            return False

        if action != "patient.clinical.read":
            return action == "patient.demographics.read"

        return (
            CareRelationship.objects.for_clinic(clinic.pk)
            .active_on(on_date)
            .filter(therapist_id=actor.pk, patient_id=patient.pk)
            .exists()
        )


__all__ = ["AuthorizationPolicy", "PatientAuthorizationPolicy"]
