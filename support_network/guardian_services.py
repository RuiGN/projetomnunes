"""Services for minor protection and guardian representation (8.16.2)."""

from __future__ import annotations

import hashlib
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from support_network.contracts import AgeTier, GuardianVerificationStatus
from support_network.events import (
    guardian_consent_disputed,
    guardian_consent_registered,
    guardian_consent_revoked,
    guardian_consent_verified,
    minor_guardrail_evaluated,
    minor_transitioned_to_adult,
)
from support_network.guardian_models import (
    LegalGuardianConsent,
    MinorPolicyVersion,
    MinorProfileGuardrail,
)


def _compute_document_hash(doc_value: str) -> str:
    """Create SHA-256 hash for document ID to protect against leaks."""
    return hashlib.sha256(doc_value.strip().encode("utf-8")).hexdigest()


@transaction.atomic
def evaluate_and_apply_minor_guardrail(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    age: int,
    is_emancipated: bool = False,
    jurisdiction: str = "BR",
    actor_id: UUID | None = None,
) -> MinorProfileGuardrail:
    """Evaluate age against versioned policies and enforce safeguarding guardrails."""
    policy = (
        MinorPolicyVersion.objects.filter(jurisdiction=jurisdiction, is_active=True)
        .order_by("-created_at")
        .first()
    )
    child_limit = policy.child_max_age if policy else 11
    young_teen_limit = policy.young_teen_max_age if policy else 15
    older_teen_limit = policy.older_teen_max_age if policy else 17

    if is_emancipated or age > older_teen_limit:
        age_tier = AgeTier.ADULT.value
        is_minor = False
    elif age <= child_limit:
        age_tier = AgeTier.CHILD.value
        is_minor = True
    elif age <= young_teen_limit:
        age_tier = AgeTier.YOUNG_TEEN.value
        is_minor = True
    else:
        age_tier = AgeTier.OLDER_TEEN.value
        is_minor = True

    # Safeguards: minors cannot be discovered publicly or message strangers
    directory_search_allowed = not is_minor
    open_messaging_allowed = not is_minor
    export_requires_guardian = is_minor

    guardrail, _ = MinorProfileGuardrail.objects.for_clinic(clinic_id).update_or_create(
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
        defaults={
            "age_tier": age_tier,
            "is_minor": is_minor,
            "is_emancipated": is_emancipated,
            "directory_search_allowed": directory_search_allowed,
            "open_messaging_allowed": open_messaging_allowed,
            "export_requires_guardian_approval": export_requires_guardian,
        },
    )

    minor_guardrail_evaluated.send(
        sender=MinorProfileGuardrail,
        guardrail=guardrail,
        age_tier=age_tier,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.guardrail_evaluated",
        resource_type="minor_guardrail",
        resource_id=str(guardrail.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return guardrail


@transaction.atomic
def register_legal_guardian_consent(
    *,
    clinic_id: UUID,
    minor_patient_id: UUID,
    guardian_name: str,
    guardian_email: str,
    guardian_phone: str,
    document_type: str,
    document_raw_id: str,
    guardian_user: AbstractBaseUser | None = None,
    verification_method: str = "ASSISTED_OPERATION",
    actor_id: UUID | None = None,
) -> LegalGuardianConsent:
    """Register legal guardian consent request awaiting formal verification."""
    doc_hash = _compute_document_hash(document_raw_id)

    consent = LegalGuardianConsent.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        minor_patient_id=minor_patient_id,
        guardian_user=cast(Any, guardian_user),
        guardian_name=guardian_name.strip(),
        guardian_email=guardian_email.strip().lower(),
        guardian_phone=guardian_phone.strip(),
        document_type=document_type.strip(),
        document_hash=doc_hash,
        verification_status=GuardianVerificationStatus.PENDING.value,
        verification_method=verification_method,
    )

    guardian_consent_registered.send(sender=LegalGuardianConsent, consent=consent)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or (guardian_user.pk if guardian_user else None),
        action="support_network.guardian_consent_registered",
        resource_type="guardian_consent",
        resource_id=str(consent.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return consent


@transaction.atomic
def verify_legal_guardian_consent(
    *,
    clinic_id: UUID,
    consent_id: UUID,
    verified_by: AbstractBaseUser,
    actor_id: UUID | None = None,
) -> LegalGuardianConsent:
    """Validate and verify legal guardian proof of custody/representation."""
    consent = (
        LegalGuardianConsent.objects.for_clinic(clinic_id).filter(id=consent_id).first()
    )
    if not consent:
        raise ValueError("Consentimento de responsável não encontrado.")

    now = timezone.now()
    consent.verification_status = GuardianVerificationStatus.VERIFIED.value
    consent.verified_at = now
    consent.verified_by = cast(Any, verified_by)
    consent.last_reviewed_at = now
    consent.save(
        update_fields=[
            "verification_status",
            "verified_at",
            "verified_by",
            "last_reviewed_at",
            "updated_at",
        ]
    )

    # Reflect verification on guardrail
    MinorProfileGuardrail.objects.for_clinic(clinic_id).filter(
        patient_id=consent.minor_patient_id
    ).update(guardian_consent_verified=True, updated_at=now)

    guardian_consent_verified.send(sender=LegalGuardianConsent, consent=consent)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or verified_by.pk,
        action="support_network.guardian_consent_verified",
        resource_type="guardian_consent",
        resource_id=str(consent.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return consent


@transaction.atomic
def dispute_legal_guardian_consent(
    *,
    clinic_id: UUID,
    consent_id: UUID,
    dispute_reason: str,
    actor_id: UUID | None = None,
) -> LegalGuardianConsent:
    """Flag custody dispute or contestation regarding legal representation."""
    consent = (
        LegalGuardianConsent.objects.for_clinic(clinic_id).filter(id=consent_id).first()
    )
    if not consent:
        raise ValueError("Consentimento de responsável não encontrado.")

    consent.verification_status = GuardianVerificationStatus.DISPUTED.value
    consent.dispute_reason = dispute_reason.strip()
    consent.save(update_fields=["verification_status", "dispute_reason", "updated_at"])

    # Check if there are other valid verified consents
    has_other_verified = (
        LegalGuardianConsent.objects.for_clinic(clinic_id)
        .filter(
            minor_patient_id=consent.minor_patient_id,
            verification_status=GuardianVerificationStatus.VERIFIED.value,
            revoked_at__isnull=True,
        )
        .exclude(id=consent.id)
        .exists()
    )
    if not has_other_verified:
        MinorProfileGuardrail.objects.for_clinic(clinic_id).filter(
            patient_id=consent.minor_patient_id
        ).update(guardian_consent_verified=False, updated_at=timezone.now())

    guardian_consent_disputed.send(sender=LegalGuardianConsent, consent=consent)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.guardian_consent_disputed",
        resource_type="guardian_consent",
        resource_id=str(consent.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return consent


@transaction.atomic
def revoke_legal_guardian_consent(
    *,
    clinic_id: UUID,
    consent_id: UUID,
    revoked_by: AbstractBaseUser,
    actor_id: UUID | None = None,
) -> LegalGuardianConsent:
    """Revoke parental custody link or representation upon legal status change."""
    consent = (
        LegalGuardianConsent.objects.for_clinic(clinic_id).filter(id=consent_id).first()
    )
    if not consent:
        raise ValueError("Consentimento de responsável não encontrado.")

    now = timezone.now()
    consent.verification_status = GuardianVerificationStatus.REVOKED.value
    consent.revoked_at = now
    consent.revoked_by = cast(Any, revoked_by)
    consent.save(
        update_fields=[
            "verification_status",
            "revoked_at",
            "revoked_by",
            "updated_at",
        ]
    )

    has_other_verified = (
        LegalGuardianConsent.objects.for_clinic(clinic_id)
        .filter(
            minor_patient_id=consent.minor_patient_id,
            verification_status=GuardianVerificationStatus.VERIFIED.value,
            revoked_at__isnull=True,
        )
        .exclude(id=consent.id)
        .exists()
    )
    if not has_other_verified:
        MinorProfileGuardrail.objects.for_clinic(clinic_id).filter(
            patient_id=consent.minor_patient_id
        ).update(guardian_consent_verified=False, updated_at=now)

    guardian_consent_revoked.send(sender=LegalGuardianConsent, consent=consent)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id or revoked_by.pk,
        action="support_network.guardian_consent_revoked",
        resource_type="guardian_consent",
        resource_id=str(consent.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return consent


@transaction.atomic
def transition_minor_to_adult(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    actor_id: UUID | None = None,
) -> MinorProfileGuardrail:
    """Safely transition patient to adult status upon age milestone (18 years)."""
    guardrail, _ = MinorProfileGuardrail.objects.for_clinic(clinic_id).get_or_create(
        clinic_id=clinic_id,
        patient_id=patient_profile_id,
    )
    guardrail.age_tier = AgeTier.ADULT.value
    guardrail.is_minor = False
    guardrail.directory_search_allowed = True
    guardrail.open_messaging_allowed = True
    guardrail.export_requires_guardian_approval = False
    guardrail.save()

    minor_transitioned_to_adult.send(sender=MinorProfileGuardrail, guardrail=guardrail)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="support_network.transitioned_to_adult",
        resource_type="minor_guardrail",
        resource_id=str(guardrail.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    return guardrail


__all__ = [
    "dispute_legal_guardian_consent",
    "evaluate_and_apply_minor_guardrail",
    "register_legal_guardian_consent",
    "revoke_legal_guardian_consent",
    "transition_minor_to_adult",
    "verify_legal_guardian_consent",
]
