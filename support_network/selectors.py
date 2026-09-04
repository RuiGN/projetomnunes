"""Selectors for support network, minor protections, urgent plans, and contemplation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import models
from django.utils import timezone

from core.selectors import Selector as CoreSelector
from support_network.contracts import EditorialReviewStatus
from support_network.governance_models import SupportNetworkRolloutFlag
from support_network.guardian_models import (
    LegalGuardianConsent,
    MinorProfileGuardrail,
)
from support_network.network_models import (
    SupportNetworkInvitation,
    SupportNetworkRelationship,
)
from support_network.spirituality_models import (
    ContemplativeContent,
    SpiritualityPreference,
)
from support_network.urgent_plan_models import (
    UrgentLocalResource,
    UrgentSupportContact,
    UrgentSupportPlan,
)


class Selector(CoreSelector[Any, Any]):
    """Default support network selector."""


def support_network_summary(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> dict[str, Any]:
    """Retrieve complete support network overview for a patient."""
    now = timezone.now()
    active_relationships = (
        SupportNetworkRelationship.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id, is_active=True)
        .prefetch_related("permissions")
    )
    pending_invitations = SupportNetworkInvitation.objects.for_clinic(clinic_id).filter(
        patient_id=patient_profile_id,
        status="pending",
        expires_at__gt=now,
    )
    return {
        "relationships": list(active_relationships),
        "pending_invitations": list(pending_invitations),
    }


def active_supporters_for_patient(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> list[SupportNetworkRelationship]:
    """List all active trusted supporters with valid permissions."""
    return list(
        SupportNetworkRelationship.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id, is_active=True)
        .prefetch_related("permissions")
        .order_by("-established_at")
    )


def minor_guardrails_for_patient(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> dict[str, Any]:
    """Retrieve minor protection settings and verified legal guardian consents."""
    guardrail = (
        MinorProfileGuardrail.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id)
        .first()
    )
    consents = LegalGuardianConsent.objects.for_clinic(clinic_id).filter(
        minor_patient_id=patient_profile_id,
        verification_status="verified",
        revoked_at__isnull=True,
    )
    return {
        "guardrail": guardrail,
        "verified_guardians": list(consents),
    }


def urgent_support_plan_for_patient(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> dict[str, Any]:
    """Retrieve patient urgent plan, ordered contacts, and local public resources."""
    plan = (
        UrgentSupportPlan.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id)
        .first()
    )
    contacts: list[UrgentSupportContact] = []
    region = "BR"
    if plan:
        contacts = list(plan.contacts.filter(is_active=True).order_by("priority_order"))
        region = plan.region

    resources = UrgentLocalResource.infrastructure_objects.filter(
        models.Q(clinic_id=clinic_id) | models.Q(clinic__isnull=True),
        region=region,
        is_active=True,
    ).order_by("service_type")
    return {
        "plan": plan,
        "contacts": contacts,
        "local_resources": list(resources),
    }


def contemplative_catalog_for_patient(
    *, clinic_id: UUID, patient_profile_id: UUID
) -> list[ContemplativeContent]:
    """List approved contemplative practices matching patient preferences.

    CRITICAL PRIVACY RULE: If the patient has not explicitly opted into spirituality,
    an empty list is returned. Non-adherents receive zero spiritual recommendations.
    """
    pref = (
        SpiritualityPreference.objects.for_clinic(clinic_id)
        .filter(patient_id=patient_profile_id)
        .first()
    )
    if not pref or not pref.is_enabled:
        return []

    traditions = [pref.tradition]
    if pref.secular_alternative_enabled and pref.tradition != "secular":
        traditions.append("secular")

    return list(
        ContemplativeContent.infrastructure_objects.filter(
            models.Q(clinic_id=clinic_id) | models.Q(clinic__isnull=True),
            tradition__in=traditions,
            editorial_review_status=EditorialReviewStatus.APPROVED.value,
            is_active=True,
        ).order_by("duration_minutes")
    )


def rollout_status_for_tenant(
    *, clinic_id: UUID, feature_name: str, age_tier: str
) -> bool:
    """Determine whether a support network feature flag is enabled for tenant & age."""
    flag = (
        SupportNetworkRolloutFlag.objects.for_clinic(clinic_id)
        .filter(feature_name=feature_name)
        .first()
    )
    if not flag:
        return True  # Default open if no restricting flag
    return flag.is_enabled


__all__ = [
    "Selector",
    "active_supporters_for_patient",
    "contemplative_catalog_for_patient",
    "minor_guardrails_for_patient",
    "rollout_status_for_tenant",
    "support_network_summary",
    "urgent_support_plan_for_patient",
]
