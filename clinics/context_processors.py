"""Safe shared template context for tenant-aware navigation."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest
from django.utils import timezone

from .models import ClinicConfiguration
from .policies import ClinicAuthorizationPolicy, has_active_clinic_role
from .selectors import active_clinics_for_actor
from .typing import ClinicRequest


def clinic_navigation(request: HttpRequest) -> dict[str, Any]:
    """Expose only the current actor's authorized active clinic choices."""
    clinic_request = cast(ClinicRequest, request)
    if not isinstance(request.user, AbstractBaseUser) or clinic_request.clinic is None:
        return {
            "active_clinic": None,
            "active_clinic_branding": None,
            "available_clinics": [],
            "can_manage_active_clinic": False,
            "is_patient": False,
            "is_therapist": False,
            "is_clinic_admin": False,
        }
    branding = (
        ClinicConfiguration.objects.for_clinic(clinic_request.clinic.pk)
        .only("display_name", "logo", "primary_color", "secondary_color")
        .first()
    )
    today = timezone.localdate()
    clinic_id = clinic_request.clinic.pk
    user_id = request.user.pk
    return {
        "active_clinic": clinic_request.clinic,
        "active_clinic_branding": branding,
        "available_clinics": active_clinics_for_actor(request.user),
        "can_manage_active_clinic": ClinicAuthorizationPolicy().is_allowed(
            request.user,
            clinic_request.clinic,
            "clinic.manage",
        ),
        "is_patient": has_active_clinic_role(
            clinic_id=clinic_id, user_id=user_id, role="patient", on_date=today
        ),
        "is_therapist": has_active_clinic_role(
            clinic_id=clinic_id, user_id=user_id, role="therapist", on_date=today
        ),
        "is_clinic_admin": has_active_clinic_role(
            clinic_id=clinic_id, user_id=user_id, role="clinic_admin", on_date=today
        ),
    }
