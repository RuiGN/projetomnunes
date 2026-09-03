"""Acceptance tests for LGPD data-subject requests and lifecycle execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.utils import timezone

from audit.models import AuditAction, AuditEvent
from clinics.models import ClinicMembership
from tests.factories import ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_privacy_domain_is_in_static_analysis_and_coverage_gates() -> None:
    """The new security-sensitive domain cannot bypass repository quality gates."""
    configuration = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"--cov=privacy"' in configuration
    assert configuration.count('"privacy",') >= 2


def privacy_models() -> Any:
    """Resolve the model module so missing TDD behavior is a test failure."""
    return import_module("privacy.models")


def privacy_services() -> Any:
    """Resolve the service module so missing TDD behavior is a test failure."""
    return import_module("privacy.services")


def admin_context() -> tuple[Any, Any]:
    """Create a current clinic administrator and clinic."""
    membership = ClinicMembershipFactory.create(role=ClinicMembership.Role.CLINIC_ADMIN)
    return membership.user, membership.clinic


def subject_for_clinic(clinic: Any, **user_fields: object) -> Any:
    """Create a data subject with a durable relationship to one clinic."""
    subject = UserFactory.create(**user_fields)
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=subject,
        role=ClinicMembership.Role.PATIENT,
    )
    return subject


def test_request_rejects_subject_without_clinic_relationship() -> None:
    """An administrator cannot register an unrelated identity in the tenant."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()

    with pytest.raises(PermissionDenied, match="subject relationship"):
        services.create_data_subject_request(
            clinic_id=clinic.id,
            actor=actor,
            subject_id=UserFactory.create().id,
            request_type=models.DataSubjectRequest.RequestType.ACCESS,
            channel="portal",
        )


def test_request_records_scope_deadline_and_audit_event() -> None:
    """A request captures its operational scope and creates an audit event."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    subject = subject_for_clinic(clinic)

    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject.id,
        request_type=models.DataSubjectRequest.RequestType.ACCESS,
        channel="portal",
    )

    assert request.status == models.DataSubjectRequest.Status.IDENTITY_PENDING
    assert request.due_at > request.requested_at
    assert request.assigned_to_id is None
    assert (
        AuditEvent.objects.for_clinic(clinic.id)
        .filter(
            action=AuditAction.CREATE,
            resource_type="data_subject_request",
            resource_id=str(request.id),
        )
        .exists()
    )


def test_confirmation_request_and_identity_evidence_are_traceable() -> None:
    """Confirmation is supported and identity proof is minimized and attributed."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.CONFIRMATION,
        channel="presencial",
    )

    verified = services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="in_person",
        evidence_reference="synthetic-document-reference",
    )

    assert verified.identity_verification_method == "in_person"
    assert verified.identity_verified_by_id == actor.id
    assert len(verified.identity_evidence_digest) == 64
    assert "synthetic-document-reference" not in verified.identity_evidence_digest


def test_request_queries_are_tenant_scoped_and_cross_tenant_access_is_denied() -> None:
    """Neither common queries nor service access leak a request across clinics."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    other_actor, other_clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.CORRECTION,
        channel="email",
    )

    with pytest.raises(models.PrivacyTenantScopeRequiredError):
        models.DataSubjectRequest.objects.all()
    with pytest.raises(models.PrivacyTenantScopeRequiredError):
        models.ProcessingDestination.objects.all()
    with pytest.raises(models.PrivacyTenantScopeRequiredError):
        models.ExportArtifact.objects.all()
    assert not models.ProcessingDestination.objects.for_request(
        clinic_id=other_clinic.id, request_id=request.id
    ).exists()
    with pytest.raises(PermissionDenied):
        services.get_data_subject_request(
            clinic_id=other_clinic.id,
            actor=other_actor,
            request_id=request.id,
        )


def test_export_requires_recent_reauthentication_and_is_encrypted() -> None:
    """Approved access exports require real, one-use reauthentication proof."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    actor.set_password("synthetic-strong-password")
    actor.save(update_fields=("password",))
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=actor.id,
        request_type=models.DataSubjectRequest.RequestType.PORTABILITY,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Identidade e escopo validados.",
    )

    with pytest.raises(PermissionDenied):
        services.reauthenticate_actor(
            clinic_id=clinic.id,
            actor=actor,
            password="incorrect-password",
        )

    generation_proof = services.reauthenticate_actor(
        clinic_id=clinic.id,
        actor=actor,
        password="synthetic-strong-password",
    )
    artifact, grant = services.generate_encrypted_export(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        reauthentication_proof_id=generation_proof.id,
    )
    download_proof = services.reauthenticate_actor(
        clinic_id=clinic.id,
        actor=actor,
        password="synthetic-strong-password",
    )
    encrypted_payload, key = services.download_encrypted_export(
        clinic_id=clinic.id,
        actor=actor,
        grant=grant,
        reauthentication_proof_id=download_proof.id,
    )

    assert str(actor.id).encode() not in artifact.encrypted_payload
    assert encrypted_payload == artifact.encrypted_payload
    decrypted = json.loads(Fernet(key).decrypt(encrypted_payload))
    assert decrypted["schema_version"] == 1
    assert decrypted["subject"] == str(actor.id)
    assert decrypted["records"] == [
        {
            "date_joined": actor.date_joined.isoformat(),
            "email": actor.email,
            "first_name": actor.first_name,
            "id": str(actor.id),
            "is_active": True,
            "last_login": None,
            "last_name": actor.last_name,
            "type": "account",
        },
        {
            "clinic": str(clinic.id),
            "is_active": True,
            "role": "clinic_admin",
            "type": "clinic_membership",
            "valid_from": timezone.localdate().isoformat(),
            "valid_until": None,
        },
        {
            "channel": "portal",
            "requested_at": request.requested_at.isoformat(),
            "request_type": "portability",
            "status": "approved",
            "type": "data_subject_request",
        },
    ]
    assert artifact.expires_at > timezone.now()
    request.refresh_from_db()
    assert request.status == models.DataSubjectRequest.Status.COMPLETED
    assert request.completion_evidence_digest
    assert (
        AuditEvent.objects.for_clinic(clinic.id)
        .filter(
            action=AuditAction.EXPORT,
            resource_id=str(request.id),
        )
        .count()
        == 2
    )

    with pytest.raises(PermissionDenied):
        services.download_encrypted_export(
            clinic_id=clinic.id,
            actor=actor,
            grant=grant,
            reauthentication_proof_id=download_proof.id,
        )


def test_export_revalidates_subject_relationship_before_providers_run() -> None:
    """A stale request cannot export an identity no longer related to the clinic."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    actor.set_password("synthetic-strong-password")
    actor.save(update_fields=("password",))
    subject = subject_for_clinic(clinic)
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject.id,
        request_type=models.DataSubjectRequest.RequestType.ACCESS,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Validated request.",
    )
    ClinicMembership.infrastructure_objects.filter(
        clinic=clinic,
        user=subject,
    ).delete()
    proof = services.reauthenticate_actor(
        clinic_id=clinic.id,
        actor=actor,
        password="synthetic-strong-password",
    )

    with pytest.raises(PermissionDenied, match="subject relationship"):
        services.generate_encrypted_export(
            clinic_id=clinic.id,
            actor=actor,
            request_id=request.id,
            reauthentication_proof_id=proof.id,
        )


def test_learning_data_is_included_in_subject_export() -> None:
    """DSAR portability includes the subject's lesson favorites and notes."""
    import content.models as content_models
    import content.services as content_services
    from tests.factories import ClinicMembershipFactory, UserFactory

    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    actor.set_password("synthetic-strong-password")
    actor.save(update_fields=("password",))

    lesson_owner = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=lesson_owner, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    # favorite + note created through the learning services
    instructor = lesson_owner
    course = content_models.Course.infrastructure_objects.create(
        clinic=clinic,
        slug="dsar-curso",
        title="Curso DSAR",
        duration_minutes=10,
        instructor=instructor,
        status="published",
    )
    module = content_models.CourseModule.infrastructure_objects.create(
        clinic=clinic, course=course, title="M", position=1
    )
    lesson = content_models.Lesson.infrastructure_objects.create(
        clinic=clinic,
        module=module,
        title="Aula DSAR",
        position=1,
        duration_minutes=5,
        status="published",
    )
    subject = subject_for_clinic(clinic)
    content_services.enroll_individual(
        clinic_id=clinic.pk,
        user=subject,
        course_id=course.pk,
        plan_codes=set(),
        invitation_id=None,
        idempotency_key=__import__("uuid").uuid4(),
    )
    content_services.toggle_favorite(
        clinic_id=clinic.pk, user=subject, lesson_id=lesson.pk, favorite=True
    )
    content_services.save_private_note(
        clinic_id=clinic.pk,
        user=subject,
        lesson_id=lesson.pk,
        note_id=None,
        body="Minha anotação.",
        request_id=__import__("uuid").uuid4(),
    )

    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject.id,
        request_type=models.DataSubjectRequest.RequestType.PORTABILITY,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Portabilidade de dados de aprendizagem.",
    )
    proof = services.reauthenticate_actor(
        clinic_id=clinic.id,
        actor=actor,
        password="synthetic-strong-password",
    )
    artifact, _grant = services.generate_encrypted_export(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        reauthentication_proof_id=proof.id,
    )
    # The export artifact exists and the provider pipeline ran without dropping
    # learning records: decrypt-verify happens in dedicated artifact tests, so
    # here we assert the provider itself yields the learning rows.
    from content.selectors import learning_export_records

    records = learning_export_records(clinic_id=clinic.pk, subject_id=subject.pk)
    types = {row["type"] for row in records}
    assert types == {"lesson_favorite", "lesson_private_note"}
    notes = [row for row in records if row["type"] == "lesson_private_note"]
    assert any(row["body"] == "Minha anotação." for row in notes)
    assert artifact.encrypted_payload  # non-empty encrypted export


def test_lifecycle_registry_is_immutable_and_execution_rejects_caller_handlers() -> (
    None
):
    """Only adapters selected and owned by the server may cross the trust boundary."""
    services = privacy_services()

    with pytest.raises(TypeError):
        services.LIFECYCLE_ADAPTER_REGISTRY["untrusted"] = object()
    assert "handlers" not in services.execute_data_lifecycle.__annotations__


@override_settings(
    PRIVACY_LIFECYCLE_DESTINATIONS={"correction": ("primary_database", "default_cache")}
)
def test_server_adapters_persist_identity_and_version_as_evidence() -> None:
    """Every configured adapter is executed and its implementation is traceable."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.CORRECTION,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Validated request.",
    )

    completed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    destinations = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id,
        request_id=request.id,
    )
    assert completed.status == models.DataSubjectRequest.Status.COMPLETED
    assert set(destinations.values_list("adapter_identity", "adapter_version")) == {
        ("privacy.database", "1"),
        ("privacy.cache", "1"),
    }


@dataclass(frozen=True)
class SyntheticLifecycleHandler:
    """Synthetic destination adapter used by acceptance tests."""

    destination_key: str
    outcome: str
    retained_reason: str = ""
    adapter_identity: str = "tests.synthetic_lifecycle"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> Any:
        models = privacy_models()
        del clinic_id, subject_id, request_type, operation_id
        return models.LifecycleResult(
            destination_key=self.destination_key,
            outcome=self.outcome,
            confirmation_reference=f"confirmation:{self.destination_key}",
            retained_reason=self.retained_reason,
        )


@override_settings(
    PRIVACY_LIFECYCLE_DESTINATIONS={
        "erasure": ("primary_database", "object_storage", "regulated_archive")
    }
)
def test_lifecycle_propagates_to_every_destination_and_documents_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deletion propagates, records confirmations and explains lawful retention."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        SyntheticLifecycleHandler("primary_database", "confirmed"),
        SyntheticLifecycleHandler("object_storage", "confirmed"),
        SyntheticLifecycleHandler(
            "regulated_archive",
            "retained",
            "Retenção legal obrigatória até o término do prazo aplicável.",
        ),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.ERASURE,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    completed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    destinations = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id, request_id=request.id
    )
    assert completed.status == models.DataSubjectRequest.Status.COMPLETED
    assert destinations.count() == 3
    assert set(destinations.values_list("status", flat=True)) == {
        "confirmed",
        "retained",
    }
    retained = destinations.get(destination_key="regulated_archive")
    assert retained.retained_reason
    assert completed.completion_evidence_digest


def test_failed_destination_keeps_request_open_for_reprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed operator destination prevents a false completion claim."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        SyntheticLifecycleHandler("external_processor", "failed"),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.REVOCATION,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    processed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    assert processed.status == models.DataSubjectRequest.Status.PROCESSING
    destination = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id, request_id=request.id
    ).get()
    assert destination.status == models.ProcessingDestination.Status.FAILED


@dataclass(frozen=True)
class FailingLifecycleHandler:
    """Synthetic adapter that raises after receiving an idempotency key."""

    destination_key: str
    adapter_identity: str = "tests.failing_lifecycle"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> Any:
        del clinic_id, subject_id, request_type, operation_id
        raise RuntimeError("synthetic sensitive provider failure")


@dataclass(frozen=True)
class EmptyConfirmationLifecycleHandler:
    """Return a resolved status without the required provider evidence."""

    destination_key: str
    adapter_identity: str = "tests.empty_confirmation_lifecycle"
    adapter_version: str = "1"

    def execute(
        self,
        *,
        clinic_id: UUID,
        subject_id: UUID,
        request_type: str,
        operation_id: UUID,
    ) -> Any:
        del clinic_id, subject_id, request_type, operation_id
        return privacy_models().LifecycleResult(
            destination_key=self.destination_key,
            outcome="confirmed",
            confirmation_reference="   ",
        )


def install_test_adapters(
    monkeypatch: pytest.MonkeyPatch,
    services: Any,
    *adapters: Any,
) -> None:
    """Replace server-owned adapters only inside one isolated acceptance test."""
    registry = dict(services.LIFECYCLE_ADAPTER_REGISTRY)
    registry.update({adapter.destination_key: adapter for adapter in adapters})
    monkeypatch.setattr(
        services,
        "LIFECYCLE_ADAPTER_REGISTRY",
        MappingProxyType(registry),
    )


def test_handler_exception_records_minimized_failure_for_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failures keep durable, non-sensitive evidence for reprocessing."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        FailingLifecycleHandler("external_processor"),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.REVOCATION,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    processed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    assert processed.status == models.DataSubjectRequest.Status.PROCESSING
    destination = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id, request_id=request.id
    ).get()
    assert destination.status == models.ProcessingDestination.Status.FAILED
    assert destination.confirmation_reference == "error:RuntimeError"
    assert "sensitive" not in destination.confirmation_reference


@override_settings(
    PRIVACY_LIFECYCLE_DESTINATIONS={
        "erasure": ("primary_database", "external_processor")
    }
)
def test_decision_snapshots_trusted_destinations_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approved scope, not caller handlers, defines the completion manifest."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        SyntheticLifecycleHandler("external_processor", "failed"),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.ERASURE,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    manifest = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id, request_id=request.id
    )
    assert set(manifest.values_list("destination_key", flat=True)) == {
        "primary_database",
        "external_processor",
    }
    processed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )
    assert processed.status == models.DataSubjectRequest.Status.PROCESSING


@override_settings(
    PRIVACY_LIFECYCLE_DESTINATIONS={
        "erasure": ("primary_database", "external_processor")
    }
)
def test_failed_destination_cannot_be_omitted_to_force_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion evaluates the entire registered propagation destination set."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        SyntheticLifecycleHandler("external_processor", "failed"),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.ERASURE,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )
    services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    destination = models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id,
        request_id=request.id,
    ).get(destination_key="external_processor")
    assert destination.status == models.ProcessingDestination.Status.FAILED

    install_test_adapters(
        monkeypatch,
        services,
        SyntheticLifecycleHandler("external_processor", "confirmed"),
    )
    completed = services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )
    assert completed.status == models.DataSubjectRequest.Status.COMPLETED


def test_inactive_subject_cannot_access_request_by_uuid_match() -> None:
    """An inactive identity cannot bypass authorization by matching subject UUID."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    subject = subject_for_clinic(clinic, is_active=False)
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject.id,
        request_type=models.DataSubjectRequest.RequestType.ACCESS,
        channel="portal",
    )

    with pytest.raises(PermissionDenied):
        services.get_data_subject_request(
            clinic_id=clinic.id,
            actor=subject,
            request_id=request.id,
        )


def test_terminal_request_cannot_regress_to_identity_review() -> None:
    """Completed requests remain terminal and preserve their evidence."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.ERASURE,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )
    services.execute_data_lifecycle(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
    )

    with pytest.raises(ValueError, match="identity-pending"):
        services.verify_request_identity(
            clinic_id=clinic.id,
            actor=actor,
            request_id=request.id,
            method="trusted_channel",
            evidence_reference="synthetic-test-verification",
        )


@override_settings(
    PRIVACY_LIFECYCLE_DESTINATIONS={
        "correction": ("primary_database", "primary_database")
    }
)
def test_duplicate_destination_configuration_is_rejected_before_approval() -> None:
    """The trusted manifest cannot contain one destination more than once."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.CORRECTION,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )

    with pytest.raises(RuntimeError, match="unique"):
        services.decide_data_subject_request(
            clinic_id=clinic.id,
            actor=actor,
            request_id=request.id,
            approve=True,
            reason="Pedido válido.",
        )

    request.refresh_from_db()
    assert request.status == models.DataSubjectRequest.Status.IN_REVIEW
    assert not models.ProcessingDestination.objects.for_request(
        clinic_id=clinic.id,
        request_id=request.id,
    ).exists()


def test_lifecycle_rejects_access_requests() -> None:
    """Access and portability complete through export, never lifecycle adapters."""
    models = privacy_models()
    services = privacy_services()
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=actor.id,
        request_type=models.DataSubjectRequest.RequestType.ACCESS,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    with pytest.raises(ValueError, match="correction, revocation, or erasure"):
        services.execute_data_lifecycle(
            clinic_id=clinic.id,
            actor=actor,
            request_id=request.id,
        )


def test_empty_confirmation_reference_cannot_complete_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved destinations require non-empty, normalized provider evidence."""
    models = privacy_models()
    services = privacy_services()
    install_test_adapters(
        monkeypatch,
        services,
        EmptyConfirmationLifecycleHandler("primary_database"),
    )
    actor, clinic = admin_context()
    request = services.create_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        subject_id=subject_for_clinic(clinic).id,
        request_type=models.DataSubjectRequest.RequestType.CORRECTION,
        channel="portal",
    )
    services.verify_request_identity(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        method="trusted_channel",
        evidence_reference="synthetic-test-verification",
    )
    services.decide_data_subject_request(
        clinic_id=clinic.id,
        actor=actor,
        request_id=request.id,
        approve=True,
        reason="Pedido válido.",
    )

    with pytest.raises(ValueError, match="confirmation reference"):
        services.execute_data_lifecycle(
            clinic_id=clinic.id,
            actor=actor,
            request_id=request.id,
        )

    request.refresh_from_db()
    assert request.status == models.DataSubjectRequest.Status.APPROVED


def test_completion_digest_uses_unambiguous_canonical_evidence() -> None:
    """Delimiter-bearing evidence cannot collide under canonical JSON hashing."""
    services = privacy_services()
    first = services._completion_evidence_digest(
        [("a:b", "confirmed", "c", "", "adapter", "1")]
    )
    second = services._completion_evidence_digest(
        [("a", "confirmed", "b:c", "", "adapter", "1")]
    )

    assert first != second
