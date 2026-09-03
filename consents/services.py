"""Transactional services for versioned consent publication and decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.selectors import (
    subject_has_active_clinic_relationship,
)
from clinics.services import (
    clinic_exists,
    lock_clinic_for_update,
    suspend_expired_memberships,
)
from core.services import Service as Service
from people.services import suspend_inconsistent_care_relationships

from .adapters import REVOCATION_ADAPTER_REGISTRY
from .integrity import (
    ConsentDocumentIntegrityError,
    publication_payload,
    require_document_integrity,
)
from .models import (
    AccessReviewException,
    AccessReviewRun,
    ConsentDocument,
    ConsentManifestation,
    ConsentRevocationDispatch,
    ConsentRevocationDispatchAttempt,
    ConsentRevocationWorkItem,
    LegalRepresentation,
)
from .policies import (
    ConsentPurpose,
    PurposeClassification,
    basic_right_purposes,
    purpose_definition,
)

__all__ = [
    "PurposeAccess",
    "ConsentDocumentIntegrityError",
    "AccessReviewReport",
    "Service",
    "publish_consent_document",
    "acknowledge_revocation_work_item",
    "process_revocation_dispatch",
    "record_consent_manifestation",
    "register_legal_representation",
    "resolve_access_review_exception",
    "review_access_lifecycle",
    "revoke_consent",
    "require_purpose_access",
    "resolve_purpose_access",
    "transition_legal_representation",
]

_ROLE_VALUES = ("clinic_admin", "therapist", "administrative_staff", "patient")
_BASIC_RIGHT_PURPOSES = frozenset(str(item) for item in basic_right_purposes())


@dataclass(frozen=True, slots=True)
class PurposeAccess:
    """Explain whether one consent-dependent purpose may proceed."""

    allowed: bool
    explanation: str
    document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AccessReviewReport:
    """Tenant-scoped evidence from one current access lifecycle review."""

    run_id: UUID
    reviewed_at: datetime
    exceptions: tuple[AccessReviewException, ...]


@transaction.atomic
def acknowledge_revocation_work_item(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    work_item_id: UUID,
    acknowledgement_reference: str,
) -> ConsentRevocationWorkItem:
    """Acknowledge durable operational handling by an active clinic administrator."""
    actor_id = _actor_id(actor)
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied("Somente a administração pode reconhecer esta tarefa.")
    reference = acknowledgement_reference.strip()
    if not reference:
        raise ValidationError("Informe a referência do atendimento operacional.")
    work_item = (
        ConsentRevocationWorkItem.infrastructure_objects.select_for_update()
        .filter(dispatch__clinic_id=clinic_id, pk=work_item_id)
        .first()
    )
    if work_item is None:
        raise ValidationError("Tarefa operacional indisponível.")
    if work_item.status == ConsentRevocationWorkItem.Status.ACKNOWLEDGED:
        return cast(ConsentRevocationWorkItem, work_item)
    work_item.status = ConsentRevocationWorkItem.Status.ACKNOWLEDGED
    work_item.acknowledged_at = timezone.now()
    work_item.acknowledged_by_id = actor_id
    work_item.acknowledgement_digest = salted_hmac(
        "consents.revocation-work-item",
        reference,
        algorithm="sha256",
    ).hexdigest()
    work_item._save_acknowledgement()
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="permission_change",
        resource_type="consent_revocation_work_item",
        resource_id=str(work_item.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=work_item.acknowledgement_digest,
    )
    return cast(ConsentRevocationWorkItem, work_item)


@transaction.atomic
def process_revocation_dispatch(
    *, clinic_id: UUID, dispatch_id: UUID
) -> ConsentRevocationDispatch:
    """Execute one persisted destination through the trusted adapter registry."""
    lock_clinic_for_update(clinic_id=clinic_id)
    dispatch = (
        ConsentRevocationDispatch.infrastructure_objects.select_for_update()
        .select_related("manifestation")
        .filter(clinic_id=clinic_id, pk=dispatch_id)
        .first()
    )
    if dispatch is None:
        raise ValidationError("Despacho de revogação indisponível.")
    if dispatch.status == ConsentRevocationDispatch.Status.CONFIRMED:
        return cast(ConsentRevocationDispatch, dispatch)
    adapter = REVOCATION_ADAPTER_REGISTRY.get(dispatch.destination)
    evidence_reference: str
    succeeded = False
    if adapter is None:
        adapter_identity = "consents.unregistered_destination"
        adapter_version = "0"
        evidence_reference = "destination:not-registered"
    else:
        adapter_identity = adapter.adapter_identity
        adapter_version = adapter.adapter_version
        try:
            result = adapter.execute(
                clinic_id=clinic_id,
                subject_id=dispatch.manifestation.subject_id,
                purpose=dispatch.manifestation.purpose,
                operation_id=dispatch.pk,
            )
        except Exception as exc:  # noqa: BLE001 - durable operational evidence
            evidence_reference = f"adapter-exception:{type(exc).__name__}"
        else:
            normalized_reference = result.confirmation_reference.strip()
            if result.destination_key != dispatch.destination:
                evidence_reference = "adapter-destination:mismatch"
            elif result.succeeded and not normalized_reference:
                evidence_reference = "confirmation-evidence:missing"
            else:
                evidence_reference = (
                    normalized_reference or "adapter-failure:unspecified"
                )
                succeeded = result.succeeded
    evidence_digest = salted_hmac(
        "consents.revocation-dispatch",
        evidence_reference,
        algorithm="sha256",
    ).hexdigest()
    previous_attempt = (
        ConsentRevocationDispatchAttempt.infrastructure_objects.filter(
            dispatch_id=dispatch.pk
        ).aggregate(value=Max("attempt_number"))["value"]
        or 0
    )
    attempt = ConsentRevocationDispatchAttempt.infrastructure_objects.create(
        clinic_id=clinic_id,
        dispatch=dispatch,
        attempt_number=previous_attempt + 1,
        outcome=(
            ConsentRevocationDispatchAttempt.Outcome.CONFIRMED
            if succeeded
            else ConsentRevocationDispatchAttempt.Outcome.FAILED
        ),
        adapter_identity=adapter_identity,
        adapter_version=adapter_version,
        evidence_digest=evidence_digest,
    )
    dispatch.adapter_identity = adapter_identity
    dispatch.adapter_version = adapter_version
    if succeeded:
        dispatch.status = ConsentRevocationDispatch.Status.CONFIRMED
        dispatch.confirmed_at = timezone.now()
        dispatch.confirmation_digest = evidence_digest
        dispatch.failure_digest = ""
    else:
        dispatch.status = ConsentRevocationDispatch.Status.FAILED
        dispatch.confirmed_at = None
        dispatch.confirmation_digest = ""
        dispatch.failure_digest = evidence_digest
    dispatch._save_lifecycle_transition(
        update_fields=(
            "adapter_identity",
            "adapter_version",
            "confirmation_digest",
            "confirmed_at",
            "failure_digest",
            "status",
        )
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=None,
        action="update",
        resource_type="consent_revocation_dispatch_attempt",
        resource_id=str(attempt.pk),
        outcome="success" if succeeded else "error",
        request_id=uuid4(),
        network_origin=None,
        justification=evidence_digest,
    )
    return cast(ConsentRevocationDispatch, dispatch)


def _actor_id(actor: AbstractBaseUser) -> UUID:
    actor_id = actor.pk
    if not isinstance(actor_id, UUID) or not actor.is_active:
        raise PermissionDenied("É necessário possuir acesso ativo à clínica.")
    return actor_id


def _active_roles(*, clinic_id: UUID, user_id: UUID) -> set[str]:
    today = timezone.localdate()
    return {
        role
        for role in _ROLE_VALUES
        if has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            on_date=today,
        )
    }


def _audiences_for_roles(roles: set[str]) -> set[str]:
    audiences = {str(ConsentDocument.Audience.ALL)}
    if "patient" in roles:
        audiences.add(str(ConsentDocument.Audience.PATIENT))
    if "therapist" in roles:
        audiences.add(str(ConsentDocument.Audience.PROFESSIONAL))
    if roles.intersection({"clinic_admin", "administrative_staff"}):
        audiences.add(str(ConsentDocument.Audience.ADMINISTRATIVE))
    return audiences


def _representation_for_purpose(
    *,
    clinic_id: UUID,
    representative_id: UUID,
    represented_subject_id: UUID,
    purpose: str,
) -> LegalRepresentation:
    today = timezone.localdate()
    representations = list(
        LegalRepresentation.infrastructure_objects.filter(
            clinic_id=clinic_id,
            representative_id=representative_id,
            represented_subject_id=represented_subject_id,
            status=LegalRepresentation.Status.VERIFIED,
            valid_from__lte=today,
            valid_until__gte=today,
            next_review_at__gte=today,
        )
    )
    for representation in representations:
        if purpose in representation.granted_purposes:
            return cast(LegalRepresentation, representation)
    if representations:
        raise ValidationError("A representação não contempla esta finalidade.")
    raise PermissionDenied("A representação não está vigente ou verificada.")


@transaction.atomic
def register_legal_representation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    representative_id: UUID,
    represented_subject_id: UUID,
    relationship_type: str,
    granted_purposes: tuple[str, ...],
    evidence_reference: str,
    valid_from: date,
    valid_until: date,
    next_review_at: date,
) -> LegalRepresentation:
    """Verify bounded representation without retaining raw evidence references."""
    actor_id = _actor_id(actor)
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied("Somente a administração pode validar representação.")
    if representative_id == represented_subject_id:
        raise ValidationError("Representante e titular devem ser pessoas distintas.")
    if not all(
        subject_has_active_clinic_relationship(
            clinic_id=clinic_id,
            subject_id=user_id,
            on_date=timezone.localdate(),
        )
        for user_id in (representative_id, represented_subject_id)
    ):
        raise PermissionDenied("As pessoas devem possuir vínculo ativo com a clínica.")
    normalized_purposes = tuple(
        dict.fromkeys(
            purpose.strip() for purpose in granted_purposes if purpose.strip()
        )
    )
    if not normalized_purposes:
        raise ValidationError("Informe ao menos uma finalidade autorizada.")
    for purpose in normalized_purposes:
        try:
            definition = purpose_definition(purpose)
        except (KeyError, ValueError) as exc:
            raise ValidationError("Finalidade de representação desconhecida.") from exc
        if definition.classification is PurposeClassification.BASIC_RIGHT:
            raise ValidationError(
                "Direitos básicos não exigem representação consentida."
            )
    normalized_evidence = evidence_reference.strip()
    if not normalized_evidence:
        raise ValidationError("A evidência de representação é obrigatória.")
    if valid_until < valid_from or not (valid_from <= next_review_at <= valid_until):
        raise ValidationError("Vigência e revisão da representação são inválidas.")
    now = timezone.now()
    representation = LegalRepresentation(
        clinic_id=clinic_id,
        representative_id=representative_id,
        represented_subject_id=represented_subject_id,
        relationship_type=relationship_type,
        granted_purposes=list(normalized_purposes),
        evidence_digest=salted_hmac(
            "consents.representation-evidence",
            normalized_evidence,
            algorithm="sha256",
        ).hexdigest(),
        valid_from=valid_from,
        valid_until=valid_until,
        verified_at=now,
        verified_by_id=actor_id,
        next_review_at=next_review_at,
    )
    representation.full_clean(validate_unique=False)
    representation.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="permission_change",
        resource_type="legal_representation",
        resource_id=str(representation.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=representation.evidence_digest,
    )
    return representation


def _transition_representation(
    *,
    representation: LegalRepresentation,
    actor_id: UUID,
    status: str,
    reason: str,
    transitioned_at: datetime,
) -> LegalRepresentation:
    """Apply and audit one already-authorized representation status transition."""
    if status not in LegalRepresentation.Status.values:
        raise ValidationError("Situação de representação inválida.")
    if representation.status == status:
        return representation
    if representation.status in {
        LegalRepresentation.Status.REVOKED,
        LegalRepresentation.Status.EXPIRED,
    }:
        raise ValidationError(
            "A situação atual da representação é terminal; "
            "a reativação exige novo registro."
        )
    if status == LegalRepresentation.Status.VERIFIED:
        raise ValidationError(
            "A reativação exige novo registro e nova evidência de representação."
        )
    representation.status = status
    representation.last_reviewed_at = transitioned_at
    representation._save_lifecycle_transition(
        update_fields=("status", "last_reviewed_at")
    )
    record_audit_event(
        clinic_id=representation.clinic_id,
        actor_id=actor_id,
        action="permission_change",
        resource_type="legal_representation",
        resource_id=str(representation.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=reason,
    )
    return representation


@transaction.atomic
def transition_legal_representation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    representation_id: UUID,
    status: str,
    reason: str,
) -> LegalRepresentation:
    """Perform an explicit audited lifecycle transition without rewriting evidence."""
    actor_id = _actor_id(actor)
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=today,
    ):
        raise PermissionDenied("Somente a administração pode alterar representação.")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("Informe o motivo da alteração da representação.")
    representation = (
        LegalRepresentation.infrastructure_objects.select_for_update()
        .filter(clinic_id=clinic_id, pk=representation_id)
        .first()
    )
    if representation is None:
        raise ValidationError("Representação indisponível.")
    return _transition_representation(
        representation=representation,
        actor_id=actor_id,
        status=status,
        reason=normalized_reason,
        transitioned_at=timezone.now(),
    )


def _persist_access_review_exception(
    *,
    run: AccessReviewRun,
    actor_id: UUID,
    resource_type: str,
    resource_id: UUID,
    reason: str,
    action: str,
) -> AccessReviewException:
    """Create or relink one deduplicated exception to the current review run."""
    exception = (
        AccessReviewException.infrastructure_objects.select_for_update()
        .filter(
            clinic_id=run.clinic_id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
        )
        .first()
    )
    if exception is not None:
        fields: list[str] = []
        reopened = exception.status == AccessReviewException.Status.RESOLVED
        if reopened:
            exception.status = AccessReviewException.Status.OPEN
            fields.append("status")
        if exception.last_seen_run_id != run.pk:
            exception.last_seen_run = run
            fields.append("last_seen_run")
        if fields:
            exception._save_lifecycle_transition(update_fields=tuple(fields))
        if reopened:
            record_audit_event(
                clinic_id=run.clinic_id,
                actor_id=actor_id,
                action="permission_change",
                resource_type="access_review_exception",
                resource_id=str(exception.pk),
                outcome="success",
                request_id=uuid4(),
                network_origin=None,
                justification=f"reopened:{reason}",
            )
        return cast(AccessReviewException, exception)
    exception = AccessReviewException.infrastructure_objects.create(
        clinic_id=run.clinic_id,
        first_run=run,
        last_seen_run=run,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        action=action,
    )
    record_audit_event(
        clinic_id=run.clinic_id,
        actor_id=actor_id,
        action="permission_change",
        resource_type=resource_type,
        resource_id=str(resource_id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=reason,
    )
    return cast(AccessReviewException, exception)


@transaction.atomic
def review_access_lifecycle(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> AccessReviewReport:
    """Persist an idempotent review and safely suspend inconsistent access."""
    actor_id = _actor_id(actor)
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=today,
    ):
        raise PermissionDenied("Somente a administração pode revisar acessos.")
    reviewed_at = timezone.now()
    lock_clinic_for_update(clinic_id=clinic_id)
    existing_run = AccessReviewRun.infrastructure_objects.filter(
        clinic_id=clinic_id,
        review_date=today,
    ).first()
    if existing_run is not None:
        existing_exceptions = tuple(
            AccessReviewException.objects.for_clinic(clinic_id)
            .filter(last_seen_run_id=existing_run.pk)
            .order_by("created_at", "id")
        )
        return AccessReviewReport(
            run_id=existing_run.pk,
            reviewed_at=existing_run.reviewed_at,
            exceptions=existing_exceptions,
        )
    run = AccessReviewRun.infrastructure_objects.create(
        clinic_id=clinic_id,
        actor_id=actor_id,
        review_date=today,
        reviewed_at=reviewed_at,
    )
    exceptions: list[AccessReviewException] = []

    for membership_id in suspend_expired_memberships(
        clinic_id=clinic_id,
        on_date=today,
    ):
        exceptions.append(
            _persist_access_review_exception(
                run=run,
                actor_id=actor_id,
                resource_type="clinic_membership",
                resource_id=membership_id,
                reason="membership_expired",
                action="suspended",
            )
        )

    for suspension in suspend_inconsistent_care_relationships(
        clinic_id=clinic_id,
        on_date=today,
    ):
        exceptions.append(
            _persist_access_review_exception(
                run=run,
                actor_id=actor_id,
                resource_type="care_relationship",
                resource_id=suspension.resource_id,
                reason=suspension.reason,
                action="suspended",
            )
        )

    representations = list(
        LegalRepresentation.infrastructure_objects.select_for_update().filter(
            Q(
                Q(status=LegalRepresentation.Status.VERIFIED)
                & (Q(valid_until__lt=today) | Q(next_review_at__lt=today))
            )
            | Q(
                status=LegalRepresentation.Status.SUSPENDED,
                valid_until__lt=today,
            ),
            clinic_id=clinic_id,
        )
    )
    for representation in representations:
        is_expired = representation.valid_until < today
        target_status = (
            LegalRepresentation.Status.EXPIRED
            if is_expired
            else LegalRepresentation.Status.SUSPENDED
        )
        reason = (
            "representation_expired" if is_expired else "representation_review_overdue"
        )
        _transition_representation(
            representation=representation,
            actor_id=actor_id,
            status=target_status,
            reason=reason,
            transitioned_at=reviewed_at,
        )
        exceptions.append(
            _persist_access_review_exception(
                run=run,
                actor_id=actor_id,
                resource_type="legal_representation",
                resource_id=representation.pk,
                reason=reason,
                action=("expired" if is_expired else "suspended"),
            )
        )

    seen_subject_purposes: set[tuple[UUID, str]] = set()
    manifestations = (
        ConsentManifestation.infrastructure_objects.filter(clinic_id=clinic_id)
        .select_related("document")
        .order_by(
            "subject_id",
            "purpose",
            "-manifested_at",
            "-sequence",
        )
    )
    for manifestation in manifestations:
        key = (manifestation.subject_id, manifestation.purpose)
        if key in seen_subject_purposes:
            continue
        seen_subject_purposes.add(key)
        if (
            manifestation.decision == ConsentManifestation.Decision.ACCEPTED
            and manifestation.document.effective_until is not None
            and manifestation.document.effective_until < reviewed_at
        ):
            exceptions.append(
                _persist_access_review_exception(
                    run=run,
                    actor_id=actor_id,
                    resource_type="consent_manifestation",
                    resource_id=manifestation.pk,
                    reason="consent_document_expired",
                    action="purpose_blocked",
                )
            )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="audit_query",
        resource_type="access_review",
        resource_id=str(run.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=f"exception_count:{len(exceptions)}",
    )
    return AccessReviewReport(
        run_id=run.pk,
        reviewed_at=reviewed_at,
        exceptions=tuple(exceptions),
    )


@transaction.atomic
def resolve_access_review_exception(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    exception_id: UUID,
    resolution_reference: str,
) -> AccessReviewException:
    """Resolve one persisted exception with minimized evidence and an audit event."""
    actor_id = _actor_id(actor)
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied("Somente a administração pode resolver exceções.")
    normalized_reference = resolution_reference.strip()
    if not normalized_reference:
        raise ValidationError("A evidência de resolução é obrigatória.")
    exception = (
        AccessReviewException.infrastructure_objects.select_for_update()
        .filter(clinic_id=clinic_id, pk=exception_id)
        .first()
    )
    if exception is None:
        raise ValidationError("Exceção de revisão indisponível.")
    if exception.status == AccessReviewException.Status.RESOLVED:
        return cast(AccessReviewException, exception)
    exception.status = AccessReviewException.Status.RESOLVED
    exception.resolved_at = timezone.now()
    exception.resolved_by_id = actor_id
    exception.resolution_digest = salted_hmac(
        "consents.access-review-resolution",
        normalized_reference,
        algorithm="sha256",
    ).hexdigest()
    exception._save_lifecycle_transition(
        update_fields=(
            "status",
            "resolved_at",
            "resolved_by",
            "resolution_digest",
        )
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="permission_change",
        resource_type="access_review_exception",
        resource_id=str(exception.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=exception.resolution_digest,
    )
    return cast(AccessReviewException, exception)


@transaction.atomic
def _publish_consent_document(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    document_type: str,
    title: str,
    version: str,
    content: str,
    purpose: str,
    effective_from: datetime,
    audience: str,
    is_mandatory: bool,
    refusal_consequence: str,
    alternative_instructions: str,
    clinic_contact_instructions: str,
    effective_until: datetime | None = None,
) -> ConsentDocument:
    """Publish one immutable version after tenant-scoped administration checks."""
    actor_id = _actor_id(actor)
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor_id,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied(
            "Somente a administração da clínica pode publicar termos."
        )
    lock_clinic_for_update(clinic_id=clinic_id)
    normalized = {
        "alternative_instructions": alternative_instructions.strip(),
        "clinic_contact_instructions": clinic_contact_instructions.strip(),
        "content": content.strip(),
        "purpose": purpose.strip(),
        "refusal_consequence": refusal_consequence.strip(),
        "title": title.strip(),
        "version": version.strip(),
    }
    if any(not value for value in normalized.values()):
        raise ValidationError(
            "Título, versão, conteúdo, finalidade, consequência, alternativa "
            "e contato são obrigatórios."
        )
    try:
        purpose_spec = purpose_definition(normalized["purpose"])
    except (KeyError, ValueError) as exc:
        raise ValidationError("Finalidade de consentimento não cadastrada.") from exc
    if purpose_spec.classification is PurposeClassification.BASIC_RIGHT:
        raise ValidationError("Direitos básicos não podem depender de consentimento.")
    if is_mandatory is not purpose_spec.is_mandatory:
        raise ValidationError(
            "A obrigatoriedade deve corresponder à classificação da finalidade."
        )
    if effective_until is not None and effective_until < effective_from:
        raise ValidationError("O término da vigência não pode anteceder seu início.")
    document = ConsentDocument(
        clinic_id=clinic_id,
        document_type=document_type,
        title=normalized["title"],
        version=normalized["version"],
        content=normalized["content"],
        purpose=normalized["purpose"],
        effective_from=effective_from,
        effective_until=effective_until,
        audience=audience,
        is_mandatory=is_mandatory,
        refusal_consequence=normalized["refusal_consequence"],
        alternative_instructions=normalized["alternative_instructions"],
        clinic_contact_instructions=normalized["clinic_contact_instructions"],
        published_at=timezone.now(),
        published_by_id=actor_id,
    )
    document.full_clean(
        exclude=("publication_hash",),
        validate_unique=False,
        validate_constraints=False,
    )
    document.publication_hash = hashlib.sha256(
        publication_payload(document)
    ).hexdigest()
    document.save(force_insert=True)
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="create",
        resource_type="consent_document",
        resource_id=str(document.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
        justification=document.publication_hash,
    )
    return document


def publish_consent_document(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    document_type: str,
    title: str,
    version: str,
    content: str,
    purpose: str,
    effective_from: datetime,
    audience: str,
    is_mandatory: bool,
    refusal_consequence: str,
    alternative_instructions: str,
    clinic_contact_instructions: str,
    effective_until: datetime | None = None,
) -> ConsentDocument:
    """Publish a document and persist minimized denied/error attempts separately."""
    request_id = uuid4()
    try:
        return _publish_consent_document(
            clinic_id=clinic_id,
            actor=actor,
            document_type=document_type,
            title=title,
            version=version,
            content=content,
            purpose=purpose,
            effective_from=effective_from,
            audience=audience,
            is_mandatory=is_mandatory,
            refusal_consequence=refusal_consequence,
            alternative_instructions=alternative_instructions,
            clinic_contact_instructions=clinic_contact_instructions,
            effective_until=effective_until,
        )
    except (PermissionDenied, ValidationError, IntegrityError) as exc:
        actor_id = actor.pk if isinstance(actor.pk, UUID) else None
        if actor_id is not None and clinic_exists(clinic_id=clinic_id):
            record_audit_event(
                clinic_id=clinic_id,
                actor_id=actor_id,
                action="create",
                resource_type="consent_document",
                resource_id=str(clinic_id),
                outcome=("denied" if isinstance(exc, PermissionDenied) else "error"),
                request_id=request_id,
                network_origin=None,
            )
        raise


def _manifestation_evidence(
    *,
    actor_id: UUID,
    subject_id: UUID,
    document: ConsentDocument,
    decision: str,
    manifested_at: datetime,
    network_origin: str | None,
    client_context: str | None,
    source: str,
) -> str:
    minimized = json.dumps(
        {
            "actor_id": str(actor_id),
            "client_context": client_context or "",
            "decision": decision,
            "document_hash": document.publication_hash,
            "manifested_at": manifested_at.isoformat(),
            "network_origin": network_origin or "",
            "source": source,
            "subject_id": str(subject_id),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return salted_hmac(
        "consents.manifestation-evidence",
        minimized,
        algorithm="sha256",
    ).hexdigest()


@transaction.atomic
def _record_consent_manifestation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subject_id: UUID,
    document_id: UUID,
    decision: str,
    request_id: UUID,
    network_origin: str | None = None,
    client_context: str | None = None,
    representation_reference: str | None = None,
    source: str = "web",
) -> ConsentManifestation:
    """Append an explicit, idempotent decision for an exact published version."""
    actor_id = _actor_id(actor)
    if not _active_roles(clinic_id=clinic_id, user_id=actor_id):
        raise PermissionDenied("É necessário possuir acesso ativo à clínica.")
    if not subject_has_active_clinic_relationship(
        clinic_id=clinic_id,
        subject_id=subject_id,
    ):
        raise PermissionDenied("Titular sem vínculo ativo com esta clínica.")
    if representation_reference:
        raise PermissionDenied(
            "Referências textuais não comprovam representação legal."
        )
    if decision not in (
        ConsentManifestation.Decision.ACCEPTED,
        ConsentManifestation.Decision.REFUSED,
    ):
        raise ValidationError(
            "A decisão explícita deve ser aceite ou recusa; "
            "revogações usam o fluxo próprio."
        )
    lock_clinic_for_update(clinic_id=clinic_id)
    document = ConsentDocument.infrastructure_objects.filter(
        pk=document_id,
        clinic_id=clinic_id,
    ).first()
    now = timezone.now()
    if document is None:
        raise ValidationError("Documento indisponível ou ainda não vigente.")
    require_document_integrity(document)
    if (
        document.published_at is None
        or not document.publication_hash
        or not document.is_active
        or document.effective_from > now
        or (document.effective_until is not None and document.effective_until < now)
    ):
        raise ValidationError("Documento indisponível ou ainda não vigente.")
    subject_roles = _active_roles(clinic_id=clinic_id, user_id=subject_id)
    if document.audience not in _audiences_for_roles(subject_roles):
        raise PermissionDenied("Documento não destinado a este titular.")
    representation = None
    if actor_id != subject_id:
        representation = _representation_for_purpose(
            clinic_id=clinic_id,
            representative_id=actor_id,
            represented_subject_id=subject_id,
            purpose=document.purpose,
        )
    replay = ConsentManifestation.infrastructure_objects.filter(
        clinic_id=clinic_id,
        request_id=request_id,
    ).first()
    if replay is not None:
        if (
            replay.actor_id == actor_id
            and replay.subject_id == subject_id
            and replay.document_id == document_id
            and replay.decision == decision
            and replay.document_hash == document.publication_hash
        ):
            return cast(ConsentManifestation, replay)
        raise ValidationError("A chave idempotente já foi usada com outra decisão.")
    latest = (
        ConsentManifestation.infrastructure_objects.filter(
            clinic_id=clinic_id,
            document_id=document_id,
            subject_id=subject_id,
        )
        .order_by("-sequence", "-manifested_at")
        .first()
    )
    if (
        latest is not None
        and latest.decision == ConsentManifestation.Decision.ACCEPTED
        and decision == ConsentManifestation.Decision.REFUSED
    ):
        raise ValidationError(
            "Uma autorização aceita só pode ser retirada pelo fluxo de revogação."
        )
    if latest is not None and latest.decision == ConsentManifestation.Decision.REVOKED:
        raise ValidationError(
            "Esta versão foi revogada e não pode ser reativada por uma nova decisão."
        )
    previous_sequence = latest.sequence if latest is not None else 0
    manifestation = ConsentManifestation.infrastructure_objects.create(
        clinic_id=clinic_id,
        document=document,
        actor_id=actor_id,
        subject_id=subject_id,
        represented_subject_id=(subject_id if representation is not None else None),
        decision=decision,
        purpose=document.purpose,
        document_hash=document.publication_hash,
        evidence_digest=_manifestation_evidence(
            actor_id=actor_id,
            subject_id=subject_id,
            document=document,
            decision=decision,
            manifested_at=now,
            network_origin=network_origin,
            client_context=client_context,
            source=source,
        ),
        representation_evidence_digest=(
            representation.evidence_digest if representation is not None else ""
        ),
        manifested_at=now,
        sequence=previous_sequence + 1,
        request_id=request_id,
        source=source,
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action=("consent_accept" if decision == "accepted" else "consent_refuse"),
        resource_type="consent_manifestation",
        resource_id=str(manifestation.pk),
        outcome="success",
        request_id=request_id,
        network_origin=network_origin,
    )
    return cast(ConsentManifestation, manifestation)


def record_consent_manifestation(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subject_id: UUID,
    document_id: UUID,
    decision: str,
    request_id: UUID,
    network_origin: str | None = None,
    client_context: str | None = None,
    representation_reference: str | None = None,
    source: str = "web",
) -> ConsentManifestation:
    """Record a decision and persist minimized denied/error attempts separately."""
    try:
        return _record_consent_manifestation(
            clinic_id=clinic_id,
            actor=actor,
            subject_id=subject_id,
            document_id=document_id,
            decision=decision,
            request_id=request_id,
            network_origin=network_origin,
            client_context=client_context,
            representation_reference=representation_reference,
            source=source,
        )
    except (PermissionDenied, ValidationError, IntegrityError) as exc:
        actor_id = actor.pk if isinstance(actor.pk, UUID) else None
        if actor_id is not None and clinic_exists(clinic_id=clinic_id):
            record_audit_event(
                clinic_id=clinic_id,
                actor_id=actor_id,
                action=(
                    "consent_accept"
                    if decision == ConsentManifestation.Decision.ACCEPTED
                    else "consent_refuse"
                ),
                resource_type="consent_document",
                resource_id=str(document_id),
                outcome=("denied" if isinstance(exc, PermissionDenied) else "error"),
                request_id=request_id,
                network_origin=network_origin,
            )
        raise


@transaction.atomic
def revoke_consent(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    subject_id: UUID,
    document_id: UUID,
    request_id: UUID,
    reason: str,
    network_origin: str | None = None,
    client_context: str | None = None,
    source: str = "web",
) -> ConsentManifestation:
    """Append a prospective revocation for one optional accepted purpose."""
    actor_id = _actor_id(actor)
    if actor_id != subject_id or not _active_roles(
        clinic_id=clinic_id,
        user_id=actor_id,
    ):
        raise PermissionDenied("Somente o titular ativo pode revogar esta autorização.")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("Informe o motivo da revogação.")
    lock_clinic_for_update(clinic_id=clinic_id)
    document = ConsentDocument.infrastructure_objects.filter(
        pk=document_id,
        clinic_id=clinic_id,
    ).first()
    if document is None:
        raise ValidationError("Documento indisponível para revogação.")
    require_document_integrity(document)
    if document.is_mandatory:
        raise ValidationError(
            "Este documento não é uma autorização opcional revogável neste fluxo."
        )
    replay = ConsentManifestation.infrastructure_objects.filter(
        clinic_id=clinic_id,
        request_id=request_id,
    ).first()
    if replay is not None:
        if (
            replay.actor_id == actor_id
            and replay.subject_id == subject_id
            and replay.document_id == document_id
            and replay.decision == ConsentManifestation.Decision.REVOKED
        ):
            return cast(ConsentManifestation, replay)
        raise ValidationError("A chave idempotente já foi usada com outra decisão.")
    latest = (
        ConsentManifestation.infrastructure_objects.filter(
            clinic_id=clinic_id,
            document_id=document_id,
            subject_id=subject_id,
        )
        .order_by("-sequence", "-manifested_at")
        .first()
    )
    if latest is None or latest.decision != ConsentManifestation.Decision.ACCEPTED:
        raise ValidationError("Não existe autorização vigente para revogar.")
    now = timezone.now()
    reason_digest = salted_hmac(
        "consents.revocation-reason",
        normalized_reason,
        algorithm="sha256",
    ).hexdigest()
    manifestation = ConsentManifestation.infrastructure_objects.create(
        clinic_id=clinic_id,
        document=document,
        actor_id=actor_id,
        subject_id=subject_id,
        represented_subject_id=None,
        decision=ConsentManifestation.Decision.REVOKED,
        purpose=document.purpose,
        document_hash=document.publication_hash,
        evidence_digest=_manifestation_evidence(
            actor_id=actor_id,
            subject_id=subject_id,
            document=document,
            decision=ConsentManifestation.Decision.REVOKED,
            manifested_at=now,
            network_origin=network_origin,
            client_context=client_context,
            source=source,
        ),
        revocation_reason_digest=reason_digest,
        representation_evidence_digest="",
        manifested_at=now,
        sequence=latest.sequence + 1,
        request_id=request_id,
        source=source,
    )
    destinations = tuple(
        dict.fromkeys(
            destination.strip()
            for destination in settings.CONSENT_REVOCATION_DESTINATIONS
            if destination.strip()
        )
    )
    if not destinations:
        raise ValidationError("Nenhum destino de revogação está configurado.")
    ConsentRevocationDispatch.infrastructure_objects.bulk_create(
        [
            ConsentRevocationDispatch(
                clinic_id=clinic_id,
                manifestation=manifestation,
                destination=destination,
            )
            for destination in destinations
        ]
    )
    record_audit_event(
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="consent_revoke",
        resource_type="consent_manifestation",
        resource_id=str(manifestation.pk),
        outcome="success",
        request_id=request_id,
        network_origin=network_origin,
    )
    return cast(ConsentManifestation, manifestation)


def resolve_purpose_access(
    *,
    clinic_id: UUID,
    subject_id: UUID,
    purpose: str,
) -> PurposeAccess:
    """Deny unknown purposes and block only the configured dependent purpose."""
    roles = _active_roles(clinic_id=clinic_id, user_id=subject_id)
    if not roles:
        return PurposeAccess(False, "Acesso à clínica indisponível.")
    if purpose in _BASIC_RIGHT_PURPOSES:
        return PurposeAccess(
            True, "Direito básico disponível independentemente de consentimento."
        )
    now = timezone.now()
    candidates = list(
        ConsentDocument.objects.for_clinic(clinic_id).order_by(
            "document_type",
            "purpose",
            "audience",
            "-published_at",
            "-created_at",
        )
    )
    for candidate in candidates:
        require_document_integrity(candidate)
    eligible = (
        candidate
        for candidate in candidates
        if candidate.purpose == purpose
        and candidate.audience in _audiences_for_roles(roles)
        and candidate.published_at is not None
        and candidate.effective_from <= now
        and candidate.is_active
        and (candidate.effective_until is None or candidate.effective_until >= now)
    )
    documents: list[ConsentDocument] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in eligible:
        key = (candidate.document_type, candidate.purpose, candidate.audience)
        if key not in seen:
            seen.add(key)
            documents.append(candidate)
    if not documents:
        return PurposeAccess(
            False,
            "Finalidade não configurada para autorização; "
            "operação bloqueada por segurança.",
        )
    for document in documents:
        manifestation = (
            ConsentManifestation.objects.for_clinic(clinic_id)
            .filter(document_id=document.pk, subject_id=subject_id)
            .order_by("-sequence", "-manifested_at")
            .first()
        )
        if manifestation is None or manifestation.decision != "accepted":
            return PurposeAccess(
                False,
                (
                    f"{document.refusal_consequence} Alternativa: "
                    f"{document.alternative_instructions} Contato da clínica: "
                    f"{document.clinic_contact_instructions} "
                    "Seus direitos básicos permanecem acessíveis."
                ),
                document.pk,
            )
    return PurposeAccess(True, "Finalidade autorizada.", documents[-1].pk)


def require_purpose_access(
    *,
    clinic_id: UUID,
    subject_id: UUID,
    purpose: ConsentPurpose,
) -> PurposeAccess:
    """Authoritative fail-closed boundary for future dependent operations."""
    access = resolve_purpose_access(
        clinic_id=clinic_id,
        subject_id=subject_id,
        purpose=str(purpose),
    )
    if not access.allowed:
        raise PermissionDenied(access.explanation)
    return access
