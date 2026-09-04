"""Service layer for care plans, signing, and autonomy (8.14.5)."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from core.services import Service as CoreService

from .events import (
    care_plan_proposed,
    care_plan_response_received,
    care_plan_signed,
)
from .models import (
    CarePlan,
    CarePlanAction,
    CarePlanPatientResponse,
    CarePlanStatus,
    PatientResponseChoice,
)
from .policies import can_prescribe_care_plan


class Service(CoreService[Any, Any]):
    """Care plan domain service base."""


@transaction.atomic
def propose_care_plan(
    *,
    clinic_id: UUID,
    patient_profile_id: UUID,
    professional_user: AbstractBaseUser,
    title: str,
    objective: str,
    clinical_rationale: str,
    contraindications: str = "",
    valid_from: date | None = None,
    valid_until: date | None = None,
    actions_data: list[dict[str, Any]] | None = None,
) -> CarePlan:
    """Propose a clinical care plan in DRAFT status awaiting clinician signature."""
    if not can_prescribe_care_plan(user=professional_user, clinic_id=clinic_id):
        raise ValidationError(
            "Apenas profissionais de saúde habilitados podem propor planos de cuidado."
        )

    clean_title = title.strip()
    clean_obj = objective.strip()
    clean_rationale = clinical_rationale.strip()

    if not clean_title or not clean_obj or not clean_rationale:
        raise ValidationError(
            "Título, objetivo e justificativa clínica são obrigatórios."
        )

    plan = CarePlan.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        patient_profile_id=patient_profile_id,
        prescribing_professional_id=professional_user.pk,
        title=clean_title,
        objective=clean_obj,
        clinical_rationale=clean_rationale,
        contraindications=contraindications.strip(),
        status=CarePlanStatus.DRAFT,
        version=1,
        valid_from=valid_from or timezone.localdate(),
        valid_until=valid_until,
    )

    if actions_data:
        for idx, act in enumerate(actions_data):
            CarePlanAction.objects.for_clinic(clinic_id).create(
                clinic_id=clinic_id,
                care_plan=plan,
                action_description=act["description"].strip(),
                target_frequency=act.get("frequency", "daily"),
                guidance=act.get("guidance", "").strip(),
                is_mandatory=act.get("is_mandatory", False),
                order=idx,
            )

    care_plan_proposed.send(sender=CarePlan, plan=plan)
    return plan


@transaction.atomic
def sign_care_plan(
    *,
    clinic_id: UUID,
    care_plan_id: UUID,
    signing_professional: AbstractBaseUser,
    request_id: UUID | None = None,
) -> CarePlan:
    """Digitally sign and activate care plan ensuring clinical governance."""
    if not can_prescribe_care_plan(user=signing_professional, clinic_id=clinic_id):
        raise ValidationError(
            "Apenas profissionais de saúde habilitados podem assinar planos de cuidado."
        )

    plan = CarePlan.objects.for_clinic(clinic_id).filter(pk=care_plan_id).first()
    if not plan:
        raise ValidationError("Plano de cuidado não encontrado.")

    now = timezone.now()
    secret = getattr(settings, "SECRET_KEY", "default-test-secret")
    digest = hashlib.sha256(
        f"{plan.id}:{signing_professional.pk}:{plan.version}:{now.isoformat()}:{secret}".encode()
    ).hexdigest()

    plan.status = CarePlanStatus.ACTIVE
    plan.signed_at = now
    plan.signature_digest = digest
    plan.save(update_fields=["status", "signed_at", "signature_digest", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=signing_professional.pk,
        action="routines.care_plan_signed",
        resource_type="care_plan",
        resource_id=str(plan.id),
        outcome="success",
        request_id=request_id or uuid4(),
        network_origin=None,
        justification=f"Professional signed care plan v{plan.version}",
    )

    care_plan_signed.send(sender=CarePlan, plan=plan)
    return plan


@transaction.atomic
def respond_to_care_plan(
    *,
    clinic_id: UUID,
    care_plan_id: UUID,
    decision: str,
    patient_notes: str = "",
    actor_id: UUID | None = None,
    request_id: UUID | None = None,
) -> CarePlanPatientResponse:
    """Record patient's autonomous decision regarding a proposed or active care plan."""
    plan = CarePlan.objects.for_clinic(clinic_id).filter(pk=care_plan_id).first()
    if not plan:
        raise ValidationError("Plano de cuidado não encontrado.")

    valid_choices = [c.value for c in PatientResponseChoice]
    if decision not in valid_choices:
        raise ValidationError(f"Decisão inválida: {decision}")

    response = CarePlanPatientResponse.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        care_plan=plan,
        plan_version_reviewed=plan.version,
        decision=decision,
        patient_notes=patient_notes.strip(),
        responded_at=timezone.now(),
    )

    if decision == PatientResponseChoice.PAUSED:
        plan.status = CarePlanStatus.PAUSED
        plan.save(update_fields=["status", "updated_at"])
    elif decision == PatientResponseChoice.REFUSED:
        plan.status = CarePlanStatus.REVOKED
        plan.save(update_fields=["status", "updated_at"])

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="routines.care_plan_patient_response",
        resource_type="care_plan",
        resource_id=str(plan.id),
        outcome="success",
        request_id=request_id or uuid4(),
        network_origin=None,
        justification=f"Patient responded with decision {decision}",
    )

    care_plan_response_received.send(sender=CarePlanPatientResponse, response=response)
    return response


__all__ = [
    "Service",
    "propose_care_plan",
    "respond_to_care_plan",
    "sign_care_plan",
]
