"""Transactional services for LGPD requests, exports and propagation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.utils import timezone

from accounts.selectors import identity_export_records
from audit.services import record_audit_event
from clinics.policies import has_active_clinic_role
from clinics.selectors import membership_export_records, subject_has_clinic_relationship
from content.selectors import learning_export_records
from core.services import Service as Service

from .adapters import LIFECYCLE_ADAPTER_REGISTRY
from .models import (
    DataSubjectRequest,
    ExportArtifact,
    LifecycleResult,
    ProcessingDestination,
    ReauthenticationProof,
)


class PrivacyActor(Protocol):
    """Minimal authenticated actor contract used by this domain."""

    id: UUID
    is_active: bool

    def check_password(self, raw_password: str) -> bool:
        """Verify one presented credential using the account password hasher."""
        ...


class ExportRecordProvider(Protocol):
    """Server-owned provider of authorized subject export records."""

    def __call__(self, *, clinic_id: UUID, subject_id: UUID) -> list[dict[str, object]]:
        """Return records scoped to one clinic and subject."""
        ...


def _account_export_records(
    *, clinic_id: UUID, subject_id: UUID
) -> list[dict[str, object]]:
    return identity_export_records(clinic_id=clinic_id, subject_id=subject_id)


EXPORT_RECORD_PROVIDERS: tuple[ExportRecordProvider, ...] = (
    _account_export_records,
    membership_export_records,
    learning_export_records,
)


def _is_admin(*, actor: PrivacyActor, clinic_id: UUID) -> bool:
    return actor.is_active and has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.id,
        role="clinic_admin",
        on_date=timezone.localdate(),
    )


def _audit(
    *,
    request: DataSubjectRequest,
    actor: PrivacyActor,
    action: str,
    outcome: str = "success",
) -> None:
    record_audit_event(
        clinic_id=request.clinic_id,
        actor_id=actor.id,
        action=action,
        resource_type="data_subject_request",
        resource_id=str(request.id),
        outcome=outcome,
        request_id=uuid4(),
        network_origin=None,
    )


def _required_lifecycle_destinations(request_type: str) -> tuple[str, ...]:
    """Resolve the trusted server configuration snapshotted at approval."""
    lifecycle_types = {
        DataSubjectRequest.RequestType.CORRECTION,
        DataSubjectRequest.RequestType.REVOCATION,
        DataSubjectRequest.RequestType.ERASURE,
    }
    if request_type not in lifecycle_types:
        return ()
    configured = getattr(settings, "PRIVACY_LIFECYCLE_DESTINATIONS", {})
    raw_destinations = configured.get(request_type, ())
    destinations = tuple(raw_destinations)
    if (
        not destinations
        or len(destinations) != len(set(destinations))
        or any(not isinstance(key, str) or not key.strip() for key in destinations)
    ):
        raise RuntimeError(
            "Lifecycle requests require unique, trusted destination configuration."
        )
    unknown = set(destinations).difference(LIFECYCLE_ADAPTER_REGISTRY)
    if unknown:
        raise RuntimeError("Lifecycle configuration references an unknown adapter.")
    return destinations


def _authorized_request(
    *, clinic_id: UUID, actor: PrivacyActor, request_id: UUID
) -> DataSubjectRequest:
    request = (
        DataSubjectRequest.infrastructure_objects.filter(
            id=request_id,
            clinic_id=clinic_id,
        )
        .select_for_update()
        .first()
    )
    if (
        request is None
        or not actor.is_active
        or not (
            _is_admin(actor=actor, clinic_id=clinic_id)
            or request.subject_id == actor.id
        )
    ):
        raise PermissionDenied("Data-subject request access denied.")
    return request


@transaction.atomic
def create_data_subject_request(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    subject_id: UUID,
    request_type: str,
    channel: str,
) -> DataSubjectRequest:
    """Create a request with an explicit deadline and pending identity check."""
    if not _is_admin(actor=actor, clinic_id=clinic_id):
        raise PermissionDenied(
            "Only a clinic privacy administrator may register requests."
        )
    if request_type not in DataSubjectRequest.RequestType.values:
        raise ValueError("Unsupported data-subject request type.")
    if not subject_has_clinic_relationship(
        clinic_id=clinic_id,
        subject_id=subject_id,
    ):
        raise PermissionDenied("Data-subject request subject relationship is invalid.")
    requested_at = timezone.now()
    request = DataSubjectRequest.infrastructure_objects.create(
        clinic_id=clinic_id,
        subject_id=subject_id,
        requested_by_id=actor.id,
        request_type=request_type,
        channel=channel,
        requested_at=requested_at,
        due_at=requested_at
        + timedelta(days=int(getattr(settings, "PRIVACY_REQUEST_DUE_DAYS", 15))),
    )
    _audit(request=request, actor=actor, action="create")
    return request


@transaction.atomic
def get_data_subject_request(
    *, clinic_id: UUID, actor: PrivacyActor, request_id: UUID
) -> DataSubjectRequest:
    """Return one request after tenant and actor authorization checks."""
    return _authorized_request(
        clinic_id=clinic_id,
        actor=actor,
        request_id=request_id,
    )


@transaction.atomic
def verify_request_identity(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    request_id: UUID,
    method: str,
    evidence_reference: str,
) -> DataSubjectRequest:
    """Record an explicit successful identity verification."""
    request = _authorized_request(
        clinic_id=clinic_id,
        actor=actor,
        request_id=request_id,
    )
    if not _is_admin(actor=actor, clinic_id=clinic_id):
        raise PermissionDenied("Identity verification requires an administrator.")
    if request.status != DataSubjectRequest.Status.IDENTITY_PENDING:
        raise ValueError("Only an identity-pending request may be verified.")
    allowed_methods = {"password", "in_person", "document", "trusted_channel"}
    normalized_reference = evidence_reference.strip()
    if method not in allowed_methods or not normalized_reference:
        raise ValueError("A supported method and identity evidence are required.")
    request.identity_verified_at = timezone.now()
    request.identity_verification_method = method
    request.identity_evidence_digest = hashlib.sha256(
        f"{request.id}:{method}:{normalized_reference}".encode()
    ).hexdigest()
    request.identity_verified_by_id = actor.id
    request.status = DataSubjectRequest.Status.IN_REVIEW
    request.assigned_to_id = actor.id
    request.save(
        update_fields=(
            "identity_verified_at",
            "identity_verification_method",
            "identity_evidence_digest",
            "identity_verified_by_id",
            "status",
            "assigned_to_id",
            "updated_at",
        )
    )
    _audit(request=request, actor=actor, action="update")
    return request


@transaction.atomic
def decide_data_subject_request(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    request_id: UUID,
    approve: bool,
    reason: str,
) -> DataSubjectRequest:
    """Approve or reject an identity-verified request with a reason."""
    request = _authorized_request(
        clinic_id=clinic_id,
        actor=actor,
        request_id=request_id,
    )
    if not _is_admin(actor=actor, clinic_id=clinic_id):
        raise PermissionDenied("Request decisions require an administrator.")
    if request.status != DataSubjectRequest.Status.IN_REVIEW:
        raise ValueError("Only a request in review may receive a decision.")
    if request.identity_verified_at is None or not reason.strip():
        raise ValueError("A verified identity and decision reason are required.")
    request.status = (
        DataSubjectRequest.Status.APPROVED
        if approve
        else DataSubjectRequest.Status.REJECTED
    )
    request.decision_reason = reason.strip()
    request.decided_at = timezone.now()
    request.save(
        update_fields=("status", "decision_reason", "decided_at", "updated_at")
    )
    if approve:
        ProcessingDestination.infrastructure_objects.bulk_create(
            [
                ProcessingDestination(
                    request=request,
                    destination_key=destination_key,
                    adapter_identity=LIFECYCLE_ADAPTER_REGISTRY[
                        destination_key
                    ].adapter_identity,
                    adapter_version=LIFECYCLE_ADAPTER_REGISTRY[
                        destination_key
                    ].adapter_version,
                    status=ProcessingDestination.Status.PENDING,
                )
                for destination_key in _required_lifecycle_destinations(
                    request.request_type
                )
            ]
        )
    _audit(request=request, actor=actor, action="update")
    return request


@transaction.atomic
def reauthenticate_actor(
    *, clinic_id: UUID, actor: PrivacyActor, password: str
) -> ReauthenticationProof:
    """Verify the current password and persist short-lived, one-use evidence."""
    if not actor.is_active or not password or not actor.check_password(password):
        raise PermissionDenied("Reauthentication failed.")
    verified_at = timezone.now()
    return ReauthenticationProof.infrastructure_objects.create(
        clinic_id=clinic_id,
        actor_id=actor.id,
        verified_at=verified_at,
        expires_at=verified_at
        + timedelta(
            seconds=int(getattr(settings, "PRIVACY_REAUTH_MAX_AGE_SECONDS", 600))
        ),
    )


@transaction.atomic
def _consume_reauthentication(
    *, clinic_id: UUID, actor: PrivacyActor, proof_id: UUID
) -> None:
    """Atomically consume one server-side proof bound to this actor and clinic."""
    proof = (
        ReauthenticationProof.infrastructure_objects.select_for_update()
        .filter(id=proof_id, clinic_id=clinic_id, actor_id=actor.id)
        .first()
    )
    now = timezone.now()
    if (
        proof is None
        or not actor.is_active
        or proof.consumed_at is not None
        or proof.expires_at <= now
        or proof.verified_at > now
    ):
        raise PermissionDenied("Recent reauthentication is required.")
    proof.consumed_at = now
    proof.save(update_fields=("consumed_at", "updated_at"))


def _export_signer() -> TimestampSigner:
    return TimestampSigner(salt="privacy.export-grant")


def _completion_evidence_digest(
    evidence: Sequence[tuple[str, str, str, str, str, str]],
) -> str:
    """Hash explicit canonical evidence without delimiter ambiguity."""
    canonical = [
        {
            "adapter_identity": adapter_identity,
            "adapter_version": adapter_version,
            "confirmation_reference": confirmation,
            "destination": destination,
            "retained_reason": retention,
            "status": status,
        }
        for (
            destination,
            status,
            confirmation,
            retention,
            adapter_identity,
            adapter_version,
        ) in sorted(evidence)
    ]
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _serialize_export_payload(*, request: DataSubjectRequest) -> bytes:
    """Build a tenant-scoped, readable export from server-owned records."""
    if not subject_has_clinic_relationship(
        clinic_id=request.clinic_id,
        subject_id=request.subject_id,
    ):
        raise PermissionDenied("Data-subject export subject relationship is invalid.")
    subject_requests = (
        DataSubjectRequest.infrastructure_objects.filter(
            clinic_id=request.clinic_id,
            subject_id=request.subject_id,
        )
        .order_by("requested_at", "id")
        .values("request_type", "channel", "status", "requested_at")
    )
    records: list[dict[str, object]] = []
    for provider in EXPORT_RECORD_PROVIDERS:
        records.extend(
            provider(clinic_id=request.clinic_id, subject_id=request.subject_id)
        )
    records.extend(
        {
            "type": "data_subject_request",
            "request_type": item["request_type"],
            "channel": item["channel"],
            "status": item["status"],
            "requested_at": item["requested_at"].isoformat(),
        }
        for item in subject_requests
    )
    envelope = {
        "schema_version": 1,
        "subject": str(request.subject_id),
        "records": records,
    }
    try:
        return json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Export payload must be JSON serializable.") from error


def generate_encrypted_export(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    request_id: UUID,
    reauthentication_proof_id: UUID,
) -> tuple[ExportArtifact, str]:
    """Encrypt an approved structured export after one-use reauthentication."""
    _consume_reauthentication(
        clinic_id=clinic_id,
        actor=actor,
        proof_id=reauthentication_proof_id,
    )
    with transaction.atomic():
        request = _authorized_request(
            clinic_id=clinic_id,
            actor=actor,
            request_id=request_id,
        )
        if (
            request.status != DataSubjectRequest.Status.APPROVED
            or request.request_type
            not in {
                DataSubjectRequest.RequestType.ACCESS,
                DataSubjectRequest.RequestType.PORTABILITY,
            }
        ):
            raise PermissionDenied("This request is not approved for export.")
        plaintext = _serialize_export_payload(request=request)
        key = Fernet.generate_key()
        encrypted_payload = Fernet(key).encrypt(plaintext)
        ciphertext_digest = hashlib.sha256(encrypted_payload).hexdigest()
        expires_at = timezone.now() + timedelta(
            seconds=int(getattr(settings, "PRIVACY_EXPORT_TTL_SECONDS", 900))
        )
        artifact, _created = ExportArtifact.infrastructure_objects.update_or_create(
            request=request,
            defaults={
                "encrypted_payload": encrypted_payload,
                "payload_digest": hashlib.sha256(plaintext).hexdigest(),
                "ciphertext_digest": ciphertext_digest,
                "expires_at": expires_at,
            },
        )
        grant = _export_signer().sign_object(
            {
                "artifact_id": str(artifact.id),
                "clinic_id": str(clinic_id),
                "ciphertext_digest": ciphertext_digest,
                "key": key.decode("ascii"),
            }
        )
        _audit(request=request, actor=actor, action="export")
        return artifact, grant


def download_encrypted_export(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    grant: str,
    reauthentication_proof_id: UUID,
) -> tuple[bytes, bytes]:
    """Return an authorized artifact after consuming fresh actor proof."""
    try:
        data = _export_signer().unsign_object(
            grant,
            max_age=int(getattr(settings, "PRIVACY_EXPORT_TTL_SECONDS", 900)),
        )
    except (BadSignature, SignatureExpired) as error:
        raise PermissionDenied("Export grant is invalid or expired.") from error
    if data.get("clinic_id") != str(clinic_id):
        raise PermissionDenied("Export grant tenant mismatch.")
    _consume_reauthentication(
        clinic_id=clinic_id,
        actor=actor,
        proof_id=reauthentication_proof_id,
    )
    with transaction.atomic():
        artifact = (
            ExportArtifact.infrastructure_objects.select_related("request")
            .filter(id=data.get("artifact_id"), request__clinic_id=clinic_id)
            .first()
        )
        if (
            artifact is None
            or artifact.expires_at <= timezone.now()
            or artifact.ciphertext_digest != data.get("ciphertext_digest")
        ):
            raise PermissionDenied("Export artifact is unavailable or expired.")
        request = _authorized_request(
            clinic_id=clinic_id,
            actor=actor,
            request_id=artifact.request_id,
        )
        encrypted_payload = bytes(artifact.encrypted_payload)
        if hashlib.sha256(encrypted_payload).hexdigest() != artifact.ciphertext_digest:
            raise PermissionDenied("Export artifact integrity verification failed.")
        request.status = DataSubjectRequest.Status.COMPLETED
        request.completed_at = timezone.now()
        request.completion_evidence_digest = _completion_evidence_digest(
            [
                (
                    "encrypted_export",
                    "confirmed",
                    artifact.ciphertext_digest,
                    "",
                    "privacy.encrypted_export",
                    "1",
                )
            ]
        )
        request.save(
            update_fields=(
                "status",
                "completed_at",
                "completion_evidence_digest",
                "updated_at",
            )
        )
        _audit(request=request, actor=actor, action="export")
        return encrypted_payload, data["key"].encode("ascii")


@transaction.atomic
def execute_data_lifecycle(
    *,
    clinic_id: UUID,
    actor: PrivacyActor,
    request_id: UUID,
) -> DataSubjectRequest:
    """Execute every destination and complete only with confirmed evidence."""
    request = _authorized_request(
        clinic_id=clinic_id,
        actor=actor,
        request_id=request_id,
    )
    if not _is_admin(actor=actor, clinic_id=clinic_id):
        raise PermissionDenied("Lifecycle execution requires an administrator.")
    if request.request_type not in {
        DataSubjectRequest.RequestType.CORRECTION,
        DataSubjectRequest.RequestType.REVOCATION,
        DataSubjectRequest.RequestType.ERASURE,
    }:
        raise ValueError(
            "Lifecycle execution is limited to correction, revocation, or erasure."
        )
    if request.status not in {
        DataSubjectRequest.Status.APPROVED,
        DataSubjectRequest.Status.PROCESSING,
    }:
        raise ValueError("Only approved requests may be executed.")
    registered_destinations = ProcessingDestination.infrastructure_objects.filter(
        request=request
    )
    if not registered_destinations.exists():
        raise ValueError("Lifecycle request has no approved destination manifest.")

    request.status = DataSubjectRequest.Status.PROCESSING
    request.save(update_fields=("status", "updated_at"))
    executable_destinations = registered_destinations.exclude(
        status__in=(
            ProcessingDestination.Status.CONFIRMED,
            ProcessingDestination.Status.RETAINED,
        )
    ).order_by("destination_key")
    for destination in executable_destinations:
        adapter = LIFECYCLE_ADAPTER_REGISTRY.get(destination.destination_key)
        if adapter is None:
            result = LifecycleResult(
                destination_key=destination.destination_key,
                outcome=ProcessingDestination.Status.FAILED,
                confirmation_reference="error:AdapterUnavailable",
            )
            adapter_identity = destination.adapter_identity
            adapter_version = destination.adapter_version
        else:
            adapter_identity = adapter.adapter_identity
            adapter_version = adapter.adapter_version
            operation_id = uuid5(
                NAMESPACE_URL,
                f"privacy:{request.id}:{destination.destination_key}",
            )
            try:
                result = adapter.execute(
                    clinic_id=clinic_id,
                    subject_id=request.subject_id,
                    request_type=request.request_type,
                    operation_id=operation_id,
                )
            except Exception as error:  # noqa: BLE001 - adapter boundary fails closed
                result = LifecycleResult(
                    destination_key=destination.destination_key,
                    outcome=ProcessingDestination.Status.FAILED,
                    confirmation_reference=f"error:{type(error).__name__}",
                )
        if result.destination_key != destination.destination_key:
            raise ValueError("Lifecycle destination identity mismatch.")
        if result.outcome not in ProcessingDestination.Status.values:
            raise ValueError("Unsupported lifecycle outcome.")
        if (
            result.outcome == ProcessingDestination.Status.RETAINED
            and not result.retained_reason.strip()
        ):
            raise ValueError("Retained data requires a legal justification.")
        resolved = result.outcome in {
            ProcessingDestination.Status.CONFIRMED,
            ProcessingDestination.Status.RETAINED,
        }
        normalized_confirmation = result.confirmation_reference.strip()
        if resolved and not normalized_confirmation:
            raise ValueError("Resolved data requires a confirmation reference.")
        destination.status = result.outcome
        destination.adapter_identity = adapter_identity
        destination.adapter_version = adapter_version
        destination.confirmation_reference = normalized_confirmation
        destination.retained_reason = result.retained_reason.strip()
        destination.confirmed_at = timezone.now() if resolved else None
        destination.save(
            update_fields=(
                "status",
                "adapter_identity",
                "adapter_version",
                "confirmation_reference",
                "retained_reason",
                "confirmed_at",
                "updated_at",
            )
        )
    destination_evidence = list(
        registered_destinations.order_by("destination_key").values_list(
            "destination_key",
            "status",
            "confirmation_reference",
            "retained_reason",
            "adapter_identity",
            "adapter_version",
        )
    )
    resolved_statuses = {
        ProcessingDestination.Status.CONFIRMED,
        ProcessingDestination.Status.RETAINED,
    }
    all_resolved = bool(destination_evidence) and all(
        status in resolved_statuses
        for (
            _destination,
            status,
            _confirmation,
            _retention,
            _identity,
            _version,
        ) in destination_evidence
    )
    if all_resolved:
        request.status = DataSubjectRequest.Status.COMPLETED
        request.completed_at = timezone.now()
        request.completion_evidence_digest = _completion_evidence_digest(
            destination_evidence
        )
        request.save(
            update_fields=(
                "status",
                "completed_at",
                "completion_evidence_digest",
                "updated_at",
            )
        )
    action = (
        "delete"
        if request.request_type == DataSubjectRequest.RequestType.ERASURE
        else "update"
    )
    _audit(request=request, actor=actor, action=action)
    return request


__all__ = [
    "LIFECYCLE_ADAPTER_REGISTRY",
    "PrivacyActor",
    "Service",
    "create_data_subject_request",
    "decide_data_subject_request",
    "download_encrypted_export",
    "execute_data_lifecycle",
    "generate_encrypted_export",
    "get_data_subject_request",
    "reauthenticate_actor",
    "verify_request_identity",
]
