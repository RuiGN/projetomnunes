"""Acceptance tests for versioned terms and consent manifestations."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import User
from audit.models import AuditAction, AuditEvent, AuditOutcome
from clinics.models import Clinic, ClinicMembership
from consents.forms import ConsentDecisionForm
from consents.models import (
    ConsentDocument,
    ConsentManifestation,
    ConsentTenantScopeRequiredError,
)
from consents.policies import (
    PURPOSE_CATALOG,
    ConsentPurpose,
    PurposeClassification,
    basic_right_purposes,
)
from consents.selectors import current_documents_for_actor
from consents.services import (
    ConsentDocumentIntegrityError,
    publish_consent_document,
    record_consent_manifestation,
    require_purpose_access,
    resolve_purpose_access,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def member_context(
    client: Client,
    *,
    role: str = ClinicMembership.Role.PATIENT,
) -> tuple[User, Clinic]:
    clinic = ClinicFactory.create()
    user = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=user, role=role)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()
    return user, clinic


def publish_document(
    *,
    clinic: Clinic,
    actor: User,
    purpose: str = "clinical_follow_up",
    mandatory: bool = False,
    audience: str = ConsentDocument.Audience.PATIENT,
    version: str = "1.0",
    document_type: str | None = None,
) -> ConsentDocument:
    if mandatory and purpose == ConsentPurpose.CLINICAL_FOLLOW_UP:
        purpose = ConsentPurpose.TERMS_OF_USE
    if document_type is None:
        document_type = (
            ConsentDocument.DocumentType.TERMS
            if purpose == ConsentPurpose.TERMS_OF_USE
            else ConsentDocument.DocumentType.CONSENT
        )
    return publish_consent_document(
        clinic_id=clinic.pk,
        actor=actor,
        document_type=document_type,
        title="Autorização de acompanhamento",
        version=version,
        content="Texto integral sintético e versionado.",
        purpose=purpose,
        effective_from=timezone.now() - timedelta(minutes=1),
        audience=audience,
        is_mandatory=mandatory,
        refusal_consequence="Esta finalidade ficará indisponível.",
        alternative_instructions="Use o atendimento administrativo da clínica.",
        clinic_contact_instructions="Entre em contato pelos canais institucionais.",
    )


def tamper_document_content(document: ConsentDocument) -> None:
    """Simulate storage-level corruption bypassing application safeguards."""
    table = ConsentDocument._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET "content" = %s WHERE "id" = %s',
            ["Conteúdo adulterado no armazenamento.", document.pk.hex],
        )


def test_consent_records_require_explicit_tenant_scope() -> None:
    with pytest.raises(ConsentTenantScopeRequiredError):
        ConsentDocument.objects.all()
    with pytest.raises(ConsentTenantScopeRequiredError):
        ConsentManifestation.objects.all()


def test_published_document_has_integrity_hash_and_cannot_be_silently_changed(
    client: Client,
) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )

    document = publish_document(clinic=clinic, actor=administrator, mandatory=True)

    assert len(document.publication_hash) == 64
    assert document.published_at is not None
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        action=AuditAction.CREATE,
        resource_type="consent_document",
        resource_id=str(document.pk),
        justification_digest__gt="",
    ).exists()
    document.is_active = False
    with pytest.raises(ValidationError):
        document.save()
    document.content = "Conteúdo adulterado."
    with pytest.raises(ValidationError):
        document.save()
    with pytest.raises(IntegrityError):
        publish_document(clinic=clinic, actor=administrator, mandatory=True)


def test_published_document_rejects_bulk_update_and_delete(client: Client) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)

    with pytest.raises(PermissionDenied):
        ConsentDocument.objects.for_clinic(clinic.pk).filter(pk=document.pk).update(
            content="Alteração silenciosa."
        )
    with pytest.raises(PermissionDenied):
        ConsentDocument.objects.for_clinic(clinic.pk).filter(pk=document.pk).delete()
    with pytest.raises(PermissionDenied):
        ConsentDocument.infrastructure_objects.filter(pk=document.pk).update(
            content="Alteração por manager interno."
        )
    with pytest.raises(PermissionDenied):
        ConsentDocument.infrastructure_objects.filter(pk=document.pk).delete()
    with pytest.raises(PermissionDenied):
        document.delete()


def test_consent_querysets_reject_bulk_writes_and_public_direct_creation(
    client: Client,
) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)

    with pytest.raises(PermissionDenied):
        ConsentDocument.objects.for_clinic(clinic.pk).bulk_create([document])
    with pytest.raises(PermissionDenied):
        ConsentDocument.objects.for_clinic(clinic.pk).bulk_update(
            [document], ["content"]
        )
    with pytest.raises(PermissionDenied):
        ConsentManifestation.objects.for_clinic(clinic.pk).bulk_create([])
    with pytest.raises(PermissionDenied):
        ConsentManifestation.objects.for_clinic(clinic.pk).bulk_update([], ["decision"])
    with pytest.raises(PermissionDenied):
        ConsentDocument.objects.for_clinic(clinic.pk).create(
            clinic_id=clinic.pk,
            document_type=ConsentDocument.DocumentType.CONSENT,
        )


def test_only_clinic_administrator_can_publish_and_cross_tenant_is_denied(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    with pytest.raises(PermissionDenied):
        publish_document(clinic=clinic, actor=patient)

    other_clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    with pytest.raises(PermissionDenied):
        publish_document(clinic=clinic, actor=administrator)
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        action=AuditAction.CREATE,
        resource_type="consent_document",
        resource_id=str(clinic.pk),
        outcome=AuditOutcome.DENIED,
    ).exists()


def test_manifestation_snapshots_document_purpose_and_minimized_evidence(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)

    manifestation = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
        network_origin="198.51.100.44",
        client_context="Synthetic Browser 1.0",
    )

    assert manifestation.document_hash == document.publication_hash
    assert manifestation.purpose == document.purpose
    assert manifestation.evidence_digest
    assert "198.51.100.44" not in manifestation.evidence_digest
    assert "Synthetic Browser" not in manifestation.evidence_digest
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=patient.pk,
        action=AuditAction.CONSENT_ACCEPT,
        resource_type="consent_manifestation",
        resource_id=str(manifestation.pk),
    ).exists()


def test_manifestation_rejects_unpublished_document_and_cross_tenant_subject(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    other_patient = UserFactory.create()
    other_clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=other_patient,
        role=ClinicMembership.Role.PATIENT,
    )
    draft = ConsentDocument.infrastructure_objects.create(
        clinic=clinic,
        document_type=ConsentDocument.DocumentType.CONSENT,
        title="Rascunho",
        version="1.0",
        content="Ainda não publicado.",
        purpose="communication",
        effective_from=timezone.now(),
        audience=ConsentDocument.Audience.PATIENT,
        is_mandatory=False,
    )

    with pytest.raises(ValidationError):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=draft.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=other_patient.pk,
            document_id=draft.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )


def test_representative_manifestation_remains_denied_until_validated_relationship(
    client: Client,
) -> None:
    representative, clinic = member_context(client)
    subject = UserFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=subject,
        role=ClinicMembership.Role.PATIENT,
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)

    with pytest.raises(PermissionDenied):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=representative,
            subject_id=subject.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=representative.pk,
        action=AuditAction.CONSENT_ACCEPT,
        resource_type="consent_document",
        resource_id=str(document.pk),
        outcome=AuditOutcome.DENIED,
    ).exists()
    with pytest.raises(PermissionDenied):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=representative,
            subject_id=subject.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
            representation_reference="synthetic-reviewed-reference",
        )


def test_manifestations_are_append_only_sequenced_and_idempotent(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    request_id = uuid4()

    first = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.REFUSED,
        request_id=request_id,
    )
    replay = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.REFUSED,
        request_id=request_id,
    )
    assert replay.pk == first.pk
    assert first.sequence == 1
    with pytest.raises(ValidationError):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=request_id,
        )
    second = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    assert second.sequence == 2
    with pytest.raises(PermissionDenied):
        ConsentManifestation.objects.for_clinic(clinic.pk).update(
            decision=ConsentManifestation.Decision.ACCEPTED
        )
    with pytest.raises(PermissionDenied):
        ConsentManifestation.objects.for_clinic(clinic.pk).delete()
    with pytest.raises(PermissionDenied):
        ConsentManifestation.infrastructure_objects.filter(pk=first.pk).update(
            decision=ConsentManifestation.Decision.REFUSED
        )
    with pytest.raises(PermissionDenied):
        ConsentManifestation.infrastructure_objects.filter(pk=first.pk).delete()


def test_manifestation_rejects_document_from_another_clinic(client: Client) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    other_clinic = ClinicFactory.create()

    with pytest.raises(ValidationError):
        ConsentManifestation.infrastructure_objects.create(
            clinic=other_clinic,
            document=document,
            actor=patient,
            subject=patient,
            decision=ConsentManifestation.Decision.ACCEPTED,
            purpose=document.purpose,
            document_hash=document.publication_hash,
            evidence_digest="a" * 64,
            manifested_at=timezone.now(),
            sequence=1,
            request_id=uuid4(),
        )


def test_current_documents_respect_audience_version_and_effective_date(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    old = publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
        version="1.0",
    )
    current = publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
        version="2.0",
    )
    publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="staff_operations",
        audience=ConsentDocument.Audience.ADMINISTRATIVE,
    )

    visible = list(current_documents_for_actor(clinic_id=clinic.pk, actor=patient))

    assert current in visible
    assert old not in visible
    assert all(
        item.audience != ConsentDocument.Audience.ADMINISTRATIVE for item in visible
    )


def test_consent_center_separates_required_and_optional_without_preselection(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    publish_document(clinic=clinic, actor=administrator, mandatory=True)
    publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
        version="1.0",
    )

    response = client.get(reverse("consent_center"))

    assert response.status_code == 200
    assert "Aceites necessários" in response.content.decode()
    assert "Autorizações opcionais" in response.content.decode()
    assert "Use o atendimento administrativo da clínica." in response.content.decode()
    assert "Entre em contato pelos canais institucionais." in response.content.decode()
    assert b" checked" not in response.content


def test_consent_center_static_copy_comes_from_translation_catalog(
    client: Client,
) -> None:
    _, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    publish_document(clinic=clinic, actor=administrator)

    with translation.override("en-us"):
        content = client.get(reverse("consent_center")).content.decode()

    assert "Terms and consents" in content
    assert "Record decision" in content
    assert "Termos e consentimentos" not in content


def test_request_id_is_required_by_form_and_manifestation_service(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)

    assert ConsentDecisionForm({"decision": "accepted"}).is_valid() is False
    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {"decision": ConsentManifestation.Decision.ACCEPTED},
    )
    assert response.status_code == 400
    with pytest.raises(TypeError):
        record_consent_manifestation(  # type: ignore[call-arg]
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
        )


def test_consent_decision_records_refusal_without_blocking_basic_workspace(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
    )

    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {
            "decision": ConsentManifestation.Decision.REFUSED,
            "request_id": str(uuid4()),
        },
    )

    assert response.status_code == 302
    manifestation = ConsentManifestation.objects.for_clinic(clinic.pk).get()
    assert manifestation.decision == ConsentManifestation.Decision.REFUSED
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=patient.pk,
        action=AuditAction.CONSENT_REFUSE,
        resource_type="consent_manifestation",
        resource_id=str(manifestation.pk),
    ).exists()
    assert client.get(reverse("workspace_vertical")).status_code == 200
    purpose = resolve_purpose_access(
        clinic_id=clinic.pk,
        subject_id=patient.pk,
        purpose="communication",
    )
    assert purpose.allowed is False
    assert "alternativa" in purpose.explanation.lower()
    assert "clínica" in purpose.explanation.lower()


def test_consent_center_translates_persisted_decision(client: Client) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    request_id = uuid4()
    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {
            "decision": ConsentManifestation.Decision.ACCEPTED,
            "request_id": request_id,
        },
    )
    assert response.status_code == 302

    content = client.get(reverse("consent_center")).content.decode()

    assert "Decisão registrada: Aceitou" in content
    assert "Decisão registrada: accepted" not in content


def test_purpose_gate_denies_unknown_but_never_blocks_basic_rights(
    client: Client,
) -> None:
    patient, clinic = member_context(client)

    unknown = resolve_purpose_access(
        clinic_id=clinic.pk,
        subject_id=patient.pk,
        purpose="unconfigured_secondary_use",
    )
    export = resolve_purpose_access(
        clinic_id=clinic.pk,
        subject_id=patient.pk,
        purpose="data_export",
    )

    assert unknown.allowed is False
    assert export.allowed is True


def test_basic_rights_still_require_an_active_relationship_with_the_clinic(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    unrelated_clinic = ClinicFactory.create()
    inactive_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=inactive_patient,
        role=ClinicMembership.Role.PATIENT,
        is_active=False,
    )

    for subject_id in (patient.pk, inactive_patient.pk):
        access = resolve_purpose_access(
            clinic_id=unrelated_clinic.pk,
            subject_id=subject_id,
            purpose=ConsentPurpose.DATA_ACCESS,
        )
        assert access.allowed is False
        with pytest.raises(PermissionDenied):
            require_purpose_access(
                clinic_id=unrelated_clinic.pk,
                subject_id=subject_id,
                purpose=ConsentPurpose.DATA_ACCESS,
            )

    inactive_access = resolve_purpose_access(
        clinic_id=clinic.pk,
        subject_id=inactive_patient.pk,
        purpose=ConsentPurpose.DATA_ACCESS,
    )
    assert inactive_access.allowed is False


def test_typed_purpose_catalog_preserves_all_basic_rights(client: Client) -> None:
    patient, clinic = member_context(client)

    expected_basic_rights = {
        ConsentPurpose.ACCOUNT_ACCESS,
        ConsentPurpose.CONSENT_HISTORY,
        ConsentPurpose.DATA_CONFIRMATION,
        ConsentPurpose.DATA_ACCESS,
        ConsentPurpose.DATA_CORRECTION,
        ConsentPurpose.DATA_ANONYMIZATION_BLOCKING_OR_ERASURE,
        ConsentPurpose.DATA_PORTABILITY,
        ConsentPurpose.PROCESSING_INFORMATION,
        ConsentPurpose.DATA_SHARING_INFORMATION,
        ConsentPurpose.CONSENT_REVOCATION,
        ConsentPurpose.PRIVACY_REQUEST,
        ConsentPurpose.DATA_EXPORT,
        ConsentPurpose.DATA_ERASURE,
        ConsentPurpose.AUTOMATED_DECISION_REVIEW,
        ConsentPurpose.PETITION_AUTHORITY,
    }
    assert basic_right_purposes() == expected_basic_rights
    assert all(
        PURPOSE_CATALOG[purpose].classification is PurposeClassification.BASIC_RIGHT
        for purpose in expected_basic_rights
    )
    assert all(
        resolve_purpose_access(
            clinic_id=clinic.pk,
            subject_id=patient.pk,
            purpose=purpose,
        ).allowed
        for purpose in expected_basic_rights
    )


def test_publication_rejects_unknown_purpose_and_mandatory_mismatch(
    client: Client,
) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )

    with pytest.raises(ValidationError):
        publish_document(
            clinic=clinic,
            actor=administrator,
            purpose="unregistered_purpose",
        )
    with pytest.raises(ValidationError):
        publish_document(
            clinic=clinic,
            actor=administrator,
            purpose=ConsentPurpose.COMMUNICATION,
            mandatory=True,
        )
    with pytest.raises(ValidationError):
        publish_document(
            clinic=clinic,
            actor=administrator,
            purpose=ConsentPurpose.TERMS_OF_USE,
            mandatory=False,
        )

    invalid = ConsentDocument(
        clinic=clinic,
        document_type=ConsentDocument.DocumentType.CONSENT,
        title="Documento inválido",
        version="1.0",
        content="Conteúdo.",
        purpose=ConsentPurpose.COMMUNICATION,
        effective_from=timezone.now(),
        audience=ConsentDocument.Audience.PATIENT,
        is_mandatory=True,
        refusal_consequence="Consequência.",
        alternative_instructions="Alternativa.",
        clinic_contact_instructions="Contato.",
    )
    with pytest.raises(ValidationError):
        invalid.full_clean(validate_unique=False, validate_constraints=False)


def test_purpose_gate_requires_every_simultaneously_applicable_document(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    patient_specific = publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
        audience=ConsentDocument.Audience.PATIENT,
    )
    general = publish_document(
        clinic=clinic,
        actor=administrator,
        purpose="communication",
        audience=ConsentDocument.Audience.ALL,
    )
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=general.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=patient_specific.pk,
        decision=ConsentManifestation.Decision.REFUSED,
        request_id=uuid4(),
    )

    access = resolve_purpose_access(
        clinic_id=clinic.pk,
        subject_id=patient.pk,
        purpose="communication",
    )

    assert access.allowed is False
    assert access.document_id == patient_specific.pk


def test_tampered_document_is_rejected_before_display_manifestation_and_authorization(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    tamper_document_content(document)

    with pytest.raises(ConsentDocumentIntegrityError):
        current_documents_for_actor(clinic_id=clinic.pk, actor=patient)
    with pytest.raises(ConsentDocumentIntegrityError):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )
    with pytest.raises(ConsentDocumentIntegrityError):
        resolve_purpose_access(
            clinic_id=clinic.pk,
            subject_id=patient.pk,
            purpose=ConsentPurpose.CLINICAL_FOLLOW_UP,
        )


def test_authoritative_boundary_denies_dependent_operation_and_keeps_basic_rights(
    client: Client,
) -> None:
    patient, clinic = member_context(client)

    with pytest.raises(PermissionDenied):
        require_purpose_access(
            clinic_id=clinic.pk,
            subject_id=patient.pk,
            purpose=ConsentPurpose.COMMUNICATION,
        )

    access = require_purpose_access(
        clinic_id=clinic.pk,
        subject_id=patient.pk,
        purpose=ConsentPurpose.DATA_ACCESS,
    )
    assert access.allowed is True


def test_infrastructure_managers_reject_get_or_create_and_update_or_create(
    client: Client,
) -> None:
    _, clinic = member_context(client)
    for operation in ("get_or_create", "update_or_create"):
        with pytest.raises(PermissionDenied):
            getattr(ConsentDocument.infrastructure_objects, operation)(
                pk=uuid4(),
                defaults={"clinic_id": clinic.pk},
            )
        with pytest.raises(PermissionDenied):
            getattr(ConsentManifestation.infrastructure_objects, operation)(
                pk=uuid4(),
                defaults={"clinic_id": clinic.pk},
            )


def test_integrity_is_checked_before_filtering_protected_document_fields(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    table = ConsentDocument._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET "is_active" = %s WHERE "id" = %s',
            [False, document.pk.hex],
        )

    with pytest.raises(ConsentDocumentIntegrityError):
        current_documents_for_actor(clinic_id=clinic.pk, actor=patient)
    with pytest.raises(ConsentDocumentIntegrityError):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )


def test_document_type_must_match_the_purpose_semantics(client: Client) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    with pytest.raises(ValidationError):
        publish_document(
            clinic=clinic,
            actor=administrator,
            purpose=ConsentPurpose.TERMS_OF_USE,
            mandatory=True,
            document_type=ConsentDocument.DocumentType.CONSENT,
        )
    with pytest.raises(ValidationError):
        publish_document(
            clinic=clinic,
            actor=administrator,
            purpose=ConsentPurpose.COMMUNICATION,
            document_type=ConsentDocument.DocumentType.TERMS,
        )


def test_duplicate_publication_attempt_is_audited_as_error(client: Client) -> None:
    administrator, clinic = member_context(
        client,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    publish_document(clinic=clinic, actor=administrator)

    with pytest.raises(IntegrityError):
        publish_document(clinic=clinic, actor=administrator)

    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        action=AuditAction.CREATE,
        resource_type="consent_document",
        resource_id=str(clinic.pk),
        outcome=AuditOutcome.ERROR,
    ).exists()


def test_conflicting_http_replay_returns_controlled_client_error(
    client: Client,
) -> None:
    patient, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_document(clinic=clinic, actor=administrator)
    request_id = uuid4()
    url = reverse("consent_decide", kwargs={"document_id": document.pk})
    assert (
        client.post(
            url,
            {
                "decision": ConsentManifestation.Decision.ACCEPTED,
                "request_id": request_id,
            },
        ).status_code
        == 302
    )
    client.raise_request_exception = False

    response = client.post(
        url,
        {
            "decision": ConsentManifestation.Decision.REFUSED,
            "request_id": request_id,
        },
    )

    assert response.status_code == 409
    assert "chave idempotente" in response.content.decode().lower()


def test_consent_center_translates_purpose_labels(client: Client) -> None:
    _, clinic = member_context(client)
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    publish_document(clinic=clinic, actor=administrator)

    response = client.get(reverse("consent_center"))

    assert response.status_code == 200
    assert "Finalidade: Acompanhamento clínico" in response.content.decode()
    assert "Finalidade: clinical_follow_up" not in response.content.decode()
