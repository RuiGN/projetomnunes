"""Acceptance tests for consent revocation, representation and access review."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from io import StringIO
from threading import Barrier, local
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction, AuditEvent, AuditOutcome
from clinics.models import Clinic, ClinicMembership
from clinics.services import lock_clinic_for_update
from consents import models as consent_models
from consents import services as consent_services
from consents.adapters import RevocationDispatchResult
from consents.models import (
    ConsentDocument,
    ConsentManifestation,
    ConsentRevocationDispatch,
    LegalRepresentation,
)
from consents.services import (
    process_revocation_dispatch,
    publish_consent_document,
    record_consent_manifestation,
    register_legal_representation,
    resolve_purpose_access,
    review_access_lifecycle,
    revoke_consent,
)
from people.models import CareRelationship
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def patient_context(client: Client) -> tuple[User, Clinic]:
    clinic = ClinicFactory.create()
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=patient,
        role=ClinicMembership.Role.PATIENT,
    )
    client.force_login(patient)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()
    return patient, clinic


def published_optional_document(
    *,
    clinic: Clinic,
    effective_until: datetime | None = None,
    audience: str = ConsentDocument.Audience.PATIENT,
) -> tuple[User, ConsentDocument]:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    document = publish_consent_document(
        clinic_id=clinic.pk,
        actor=administrator,
        document_type=ConsentDocument.DocumentType.CONSENT,
        title="Autorização opcional",
        version="1.0",
        content="Conteúdo sintético.",
        purpose="communication",
        effective_from=timezone.now(),
        audience=audience,
        is_mandatory=False,
        refusal_consequence="A comunicação opcional será interrompida.",
        alternative_instructions="Use os canais institucionais.",
        clinic_contact_instructions="Entre em contato com a clínica.",
        effective_until=effective_until,
    )
    return administrator, document


def accepted_revocation(
    *, patient: User, clinic: Clinic, document: ConsentDocument
) -> ConsentManifestation:
    """Create one accepted optional purpose and its pending revocation obligation."""
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    return revoke_consent(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        request_id=uuid4(),
        reason="Não desejo mais esta comunicação.",
    )


def test_revocation_is_prospective_append_only_and_audited(client: Client) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)
    accepted = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )

    revoked = revoke_consent(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        request_id=uuid4(),
        reason="Não desejo mais esta comunicação.",
    )

    assert revoked.decision == ConsentManifestation.Decision.REVOKED
    assert revoked.sequence == accepted.sequence + 1
    assert revoked.manifested_at >= accepted.manifested_at
    assert revoked.revocation_reason_digest
    assert (
        resolve_purpose_access(
            clinic_id=clinic.pk,
            subject_id=patient.pk,
            purpose="communication",
        ).allowed
        is False
    )
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=patient.pk,
        action=AuditAction.CONSENT_REVOKE,
        resource_type="consent_manifestation",
        resource_id=str(revoked.pk),
    ).exists()
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        clinic_id=clinic.pk,
        manifestation=revoked,
    )
    assert dispatch.destination == "clinic_operations"
    assert dispatch.status == ConsentRevocationDispatch.Status.PENDING
    assert not dispatch.confirmed_at
    assert not dispatch.confirmation_digest


def test_clinic_operations_requires_durable_explicit_acknowledgement(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="clinic_operations",
    )

    first_attempt = process_revocation_dispatch(
        clinic_id=clinic.pk,
        dispatch_id=dispatch.pk,
    )

    assert first_attempt.status == ConsentRevocationDispatch.Status.FAILED
    work_item_model = consent_models.ConsentRevocationWorkItem
    work_item = work_item_model.objects.for_clinic(clinic.pk).get(dispatch=dispatch)
    assert work_item.status == work_item_model.Status.OPEN
    assert not work_item.acknowledged_at
    with pytest.raises(PermissionDenied, match="administração"):
        consent_services.acknowledge_revocation_work_item(
            clinic_id=clinic.pk,
            actor=patient,
            work_item_id=work_item.pk,
            acknowledgement_reference="ticket-operacional-negado",
        )

    acknowledged = consent_services.acknowledge_revocation_work_item(
        clinic_id=clinic.pk,
        actor=administrator,
        work_item_id=work_item.pk,
        acknowledgement_reference="ticket-operacional-845-001",
    )
    confirmed = process_revocation_dispatch(
        clinic_id=clinic.pk,
        dispatch_id=dispatch.pk,
    )

    assert acknowledged.status == work_item_model.Status.ACKNOWLEDGED
    assert acknowledged.acknowledgement_digest
    assert acknowledged.acknowledged_by_id == administrator.pk
    assert confirmed.status == ConsentRevocationDispatch.Status.CONFIRMED
    assert confirmed.confirmation_digest
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            actor_id=administrator.pk,
            action=AuditAction.PERMISSION_CHANGE,
            resource_type="consent_revocation_work_item",
            resource_id=str(work_item.pk),
            outcome=AuditOutcome.SUCCESS,
        ).count()
        == 1
    )


def test_clinic_admin_consumes_revocation_work_queue_through_http(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="clinic_operations",
    )
    process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
    work_item = consent_models.ConsentRevocationWorkItem.objects.for_clinic(
        clinic.pk
    ).get(dispatch=dispatch)
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    queue = client.get(reverse("consent_revocation_work_queue"))
    notification = client.get(reverse("workspace_vertical"))
    response = client.post(
        reverse(
            "consent_revocation_work_acknowledge",
            kwargs={"work_item_id": work_item.pk},
        ),
        {"acknowledgement_reference": "ticket-http-845-001"},
    )

    assert queue.status_code == 200
    assert "Revogações aguardando tratamento" in queue.content.decode()
    assert notification.status_code == 200
    assert "1 revogação operacional pendente" in notification.content.decode()
    assert response.status_code == 302
    work_item.refresh_from_db()
    assert (
        work_item.status == consent_models.ConsentRevocationWorkItem.Status.ACKNOWLEDGED
    )


def test_revocation_queue_distinguishes_same_purpose_without_exposing_subject_uuid(
    client: Client,
) -> None:
    first_patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    second_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=second_patient,
        role=ClinicMembership.Role.PATIENT,
    )
    dispatches = []
    for patient in (first_patient, second_patient):
        revoked = accepted_revocation(
            patient=patient,
            clinic=clinic,
            document=document,
        )
        dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
            manifestation=revoked,
            destination="clinic_operations",
        )
        process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
        dispatches.append(dispatch)
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("consent_revocation_work_queue"))
    content = response.content.decode()
    references = re.findall(r"Titular:</strong>\s*([A-Z0-9-]+)", content)

    assert response.status_code == 200
    assert len(set(references)) == 2
    assert str(first_patient.pk) not in content
    assert str(second_patient.pk) not in content
    for dispatch in dispatches:
        assert str(dispatch.pk) in content


@pytest.mark.parametrize(
    "role",
    (ClinicMembership.Role.PATIENT, ClinicMembership.Role.ADMINISTRATIVE_STAFF),
)
def test_non_admin_cannot_view_or_acknowledge_revocation_work_http(
    client: Client,
    role: str,
) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="clinic_operations",
    )
    process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
    work_item = consent_models.ConsentRevocationWorkItem.objects.for_clinic(
        clinic.pk
    ).get(dispatch=dispatch)
    unauthorized = (
        patient if role == ClinicMembership.Role.PATIENT else UserFactory.create()
    )
    if role != ClinicMembership.Role.PATIENT:
        ClinicMembershipFactory.create(clinic=clinic, user=unauthorized, role=role)
    client.force_login(unauthorized)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    queue = client.get(reverse("consent_revocation_work_queue"))
    notification = client.get(reverse("workspace_vertical"))
    acknowledgement = client.post(
        reverse(
            "consent_revocation_work_acknowledge",
            kwargs={"work_item_id": work_item.pk},
        ),
        {"acknowledgement_reference": "forbidden-reference"},
    )

    assert queue.status_code == 403
    assert acknowledgement.status_code == 403
    assert "revogação operacional pendente" not in notification.content.decode()
    work_item.refresh_from_db()
    assert work_item.status == consent_models.ConsentRevocationWorkItem.Status.OPEN
    assert not AuditEvent.infrastructure_objects.filter(
        resource_type="consent_revocation_work_item",
        resource_id=str(work_item.pk),
        actor_id=unauthorized.pk,
    ).exists()


def test_admin_cannot_acknowledge_revocation_work_from_another_tenant(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="clinic_operations",
    )
    process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
    work_item = consent_models.ConsentRevocationWorkItem.objects.for_clinic(
        clinic.pk
    ).get(dispatch=dispatch)
    other_clinic = ClinicFactory.create()
    other_admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=other_admin,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(other_admin)
    session = client.session
    session["active_clinic_id"] = str(other_clinic.pk)
    session.save()

    queue = client.get(reverse("consent_revocation_work_queue"))
    acknowledgement = client.post(
        reverse(
            "consent_revocation_work_acknowledge",
            kwargs={"work_item_id": work_item.pk},
        ),
        {"acknowledgement_reference": "cross-tenant-reference"},
    )

    assert queue.status_code == 200
    assert str(dispatch.pk) not in queue.content.decode()
    assert acknowledgement.status_code == 400
    work_item.refresh_from_db()
    assert work_item.status == consent_models.ConsentRevocationWorkItem.Status.OPEN
    assert not AuditEvent.infrastructure_objects.filter(
        resource_type="consent_revocation_work_item",
        resource_id=str(work_item.pk),
        actor_id=other_admin.pk,
    ).exists()


def test_revocation_work_http_fails_closed_without_explicit_active_tenant(
    client: Client,
) -> None:
    _patient, clinic = patient_context(client)
    administrator, _document = published_optional_document(clinic=clinic)
    other_clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session.pop("active_clinic_id", None)
    session.save()

    response = client.get(reverse("consent_revocation_work_queue"))

    assert response.status_code == 400


def test_database_rejects_work_item_acknowledged_without_complete_evidence(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="clinic_operations",
    )

    with pytest.raises(IntegrityError):
        consent_models.ConsentRevocationWorkItem.infrastructure_objects.create(
            dispatch=dispatch,
            status=consent_models.ConsentRevocationWorkItem.Status.ACKNOWLEDGED,
        )


@pytest.mark.parametrize(
    ("source", "target"),
    (
        (LegalRepresentation.Status.REVOKED, LegalRepresentation.Status.SUSPENDED),
        (LegalRepresentation.Status.REVOKED, LegalRepresentation.Status.EXPIRED),
        (LegalRepresentation.Status.EXPIRED, LegalRepresentation.Status.SUSPENDED),
        (LegalRepresentation.Status.EXPIRED, LegalRepresentation.Status.REVOKED),
    ),
)
def test_terminal_representation_states_reject_every_transition(
    client: Client, source: str, target: str
) -> None:
    patient, clinic = patient_context(client)
    administrator, _document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=representative, role="patient")
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="terminal-state-matrix",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )
    consent_services.transition_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representation_id=representation.pk,
        status=source,
        reason="Encerramento.",
    )

    with pytest.raises(ValidationError, match="terminal"):
        consent_services.transition_legal_representation(
            clinic_id=clinic.pk,
            actor=administrator,
            representation_id=representation.pk,
            status=target,
            reason="Transição inválida.",
        )


def test_mandatory_document_cannot_use_optional_revocation_flow(client: Client) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    document = publish_consent_document(
        clinic_id=clinic.pk,
        actor=administrator,
        document_type=ConsentDocument.DocumentType.TERMS,
        title="Termos obrigatórios",
        version="1.0",
        content="Conteúdo sintético.",
        purpose="terms_of_use",
        effective_from=timezone.now(),
        audience=ConsentDocument.Audience.PATIENT,
        is_mandatory=True,
        refusal_consequence="O recurso contratual ficará indisponível.",
        alternative_instructions="Solicite atendimento humano.",
        clinic_contact_instructions="Entre em contato com a clínica.",
    )
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )

    with pytest.raises(ValidationError):
        revoke_consent(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            request_id=uuid4(),
            reason="Tentativa inválida.",
        )


def test_generic_decision_flow_rejects_revoked_for_mandatory_document(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    document = publish_consent_document(
        clinic_id=clinic.pk,
        actor=administrator,
        document_type=ConsentDocument.DocumentType.TERMS,
        title="Termos obrigatórios protegidos",
        version="1.0",
        content="Conteúdo sintético.",
        purpose="terms_of_use",
        effective_from=timezone.now(),
        audience=ConsentDocument.Audience.PATIENT,
        is_mandatory=True,
        refusal_consequence="O recurso ficará indisponível.",
        alternative_instructions="Solicite atendimento humano.",
        clinic_contact_instructions="Entre em contato com a clínica.",
    )
    client.force_login(patient)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {
            "request_id": str(uuid4()),
            "decision": ConsentManifestation.Decision.REVOKED,
        },
    )

    assert response.status_code == 400
    assert not ConsentManifestation.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        document=document,
        subject=patient,
        decision=ConsentManifestation.Decision.REVOKED,
    ).exists()
    assert not ConsentRevocationDispatch.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        manifestation__document=document,
        manifestation__subject=patient,
    ).exists()

    with pytest.raises(ValidationError, match="aceite ou recusa"):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=patient,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.REVOKED,
            request_id=uuid4(),
        )


def test_generic_refusal_cannot_bypass_revocation_propagation(client: Client) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    client.force_login(patient)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {
            "request_id": str(uuid4()),
            "decision": ConsentManifestation.Decision.REFUSED,
        },
    )

    assert response.status_code == 409
    assert (
        ConsentManifestation.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            document=document,
            subject=patient,
        ).count()
        == 1
    )
    assert not ConsentRevocationDispatch.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        manifestation__document=document,
        manifestation__subject=patient,
    ).exists()


def test_revoked_document_version_cannot_be_reaccepted_while_dispatch_is_pending(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    assert ConsentRevocationDispatch.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        manifestation=revoked,
        status=ConsentRevocationDispatch.Status.PENDING,
    ).exists()
    client.force_login(patient)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("consent_decide", kwargs={"document_id": document.pk}),
        {
            "request_id": str(uuid4()),
            "decision": ConsentManifestation.Decision.ACCEPTED,
        },
    )

    assert response.status_code == 409
    assert (
        ConsentManifestation.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            document=document,
            subject=patient,
        ).count()
        == 2
    )
    assert (
        resolve_purpose_access(
            clinic_id=clinic.pk,
            subject_id=patient.pk,
            purpose=document.purpose,
        ).allowed
        is False
    )


def test_verified_representation_grants_only_documented_powers(client: Client) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="synthetic-evidence-2026-001",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )

    manifestation = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=representative,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )

    assert representation.evidence_digest
    assert representation.evidence_digest != "synthetic-evidence-2026-001"
    assert manifestation.actor_id == representative.pk
    assert manifestation.subject_id == patient.pk
    assert manifestation.represented_subject_id == patient.pk
    assert (
        manifestation.representation_evidence_digest == representation.evidence_digest
    )


def test_representation_never_infers_powers_outside_verified_scope(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("clinical_follow_up",),
        evidence_reference="synthetic-evidence-2026-002",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )

    with pytest.raises(ValidationError, match="não contempla esta finalidade"):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=representative,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )


@pytest.mark.parametrize(
    "terminal_status",
    (LegalRepresentation.Status.REVOKED, LegalRepresentation.Status.EXPIRED),
)
def test_terminal_representation_cannot_return_to_verified(
    client: Client,
    terminal_status: str,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="synthetic-terminal-evidence",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )
    consent_services.transition_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representation_id=representation.pk,
        status=terminal_status,
        reason="Encerramento documentado.",
    )

    with pytest.raises(ValidationError, match="novo registro"):
        consent_services.transition_legal_representation(
            clinic_id=clinic.pk,
            actor=administrator,
            representation_id=representation.pk,
            status=LegalRepresentation.Status.VERIFIED,
            reason="Tentativa de reativação indevida.",
        )

    representation.refresh_from_db()
    assert representation.status == terminal_status


def test_suspended_representation_requires_new_record_and_current_memberships(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="synthetic-suspension-evidence",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )
    consent_services.transition_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representation_id=representation.pk,
        status=LegalRepresentation.Status.SUSPENDED,
        reason="Revisão documental necessária.",
    )
    represented_membership = ClinicMembership.infrastructure_objects.get(
        clinic=clinic,
        user=patient,
    )
    represented_membership.is_active = False
    represented_membership.save(update_fields=("is_active",))

    with pytest.raises(ValidationError, match="novo registro"):
        consent_services.transition_legal_representation(
            clinic_id=clinic.pk,
            actor=administrator,
            representation_id=representation.pk,
            status=LegalRepresentation.Status.VERIFIED,
            reason="Tentativa sem novo documento.",
        )


def test_represented_manifestation_denies_inactive_subject_for_all_audience(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(
        clinic=clinic,
        audience=ConsentDocument.Audience.ALL,
    )
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="synthetic-all-audience-evidence",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )
    membership = ClinicMembership.infrastructure_objects.get(
        clinic=clinic,
        user=patient,
    )
    membership.is_active = False
    membership.save(update_fields=("is_active",))

    with pytest.raises(PermissionDenied, match="vínculo ativo"):
        record_consent_manifestation(
            clinic_id=clinic.pk,
            actor=representative,
            subject_id=patient.pk,
            document_id=document.pk,
            decision=ConsentManifestation.Decision.ACCEPTED,
            request_id=uuid4(),
        )

    assert (
        not ConsentManifestation.objects.for_clinic(clinic.pk)
        .filter(
            document=document,
            subject=patient,
        )
        .exists()
    )
    assert not AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=representative.pk,
        action=AuditAction.CONSENT_ACCEPT,
        outcome=AuditOutcome.SUCCESS,
    ).exists()


def test_access_review_suspends_expired_access_and_reports_exceptions(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(
        clinic=clinic,
        effective_until=timezone.now() + timedelta(days=30),
    )
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    expiring_user = UserFactory.create()
    membership = ClinicMembershipFactory.create(
        clinic=clinic,
        user=expiring_user,
        role=ClinicMembership.Role.THERAPIST,
        valid_until=timezone.localdate() + timedelta(days=10),
    )
    relationship = CareRelationship.infrastructure_objects.create(
        clinic=clinic,
        therapist=expiring_user,
        patient=patient,
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=10),
    )
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=expiring_user.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.AUTHORIZED_REPRESENTATIVE,
        granted_purposes=("communication",),
        evidence_reference="synthetic-evidence-2026-003",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=20),
        next_review_at=timezone.localdate() + timedelta(days=10),
    )

    review_time = timezone.now() + timedelta(days=60)
    monkeypatch.setattr("consents.services.timezone.now", lambda: review_time)
    report = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    membership.refresh_from_db()
    relationship.refresh_from_db()
    representation.refresh_from_db()
    assert membership.is_active is False
    assert relationship.is_active is False
    assert representation.status == LegalRepresentation.Status.EXPIRED
    assert {item.resource_type for item in report.exceptions} == {
        "clinic_membership",
        "care_relationship",
        "legal_representation",
        "consent_manifestation",
    }


def test_access_review_expires_previously_suspended_representation(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _document = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    today = timezone.localdate()
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="suspended-before-expiration",
        valid_from=today,
        valid_until=today,
        next_review_at=today,
    )
    consent_services.transition_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representation_id=representation.pk,
        status=LegalRepresentation.Status.SUSPENDED,
        reason="Verificação documental pendente.",
    )
    review_time = timezone.now() + timedelta(days=1)
    monkeypatch.setattr("consents.services.timezone.now", lambda: review_time)

    report = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    representation.refresh_from_db()
    assert representation.status == LegalRepresentation.Status.EXPIRED
    assert any(
        item.resource_type == "legal_representation"
        and item.resource_id == representation.pk
        and item.reason == "representation_expired"
        for item in report.exceptions
    )


def test_patient_revokes_optional_consent_through_confirmed_accessible_flow(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)
    record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    url = reverse("consent_revoke", kwargs={"document_id": document.pk})

    center = client.get(reverse("consent_center"))
    assert center.status_code == 200
    assert url in center.content.decode()
    assert "A revogação interrompe novos usos" in center.content.decode()

    invalid = client.post(
        url,
        {"request_id": str(uuid4()), "reason": "Quero retirar a autorização."},
    )
    assert invalid.status_code == 400

    response = client.post(
        url,
        {
            "request_id": str(uuid4()),
            "reason": "Quero retirar a autorização.",
            "confirm_scope": "on",
        },
    )

    assert response.status_code == 302
    latest = (
        ConsentManifestation.objects.for_clinic(clinic.pk)
        .filter(
            document=document,
            subject=patient,
        )
        .order_by("-sequence")
        .first()
    )
    assert latest is not None
    assert latest.decision == ConsentManifestation.Decision.REVOKED


class SequencedRevocationAdapter:
    """Synthetic adapter that exposes durable failure-then-success evidence."""

    destination_key = "clinic_operations"
    adapter_identity = "tests.sequenced"
    adapter_version = "1"

    def __init__(self, results: list[RevocationDispatchResult | Exception]) -> None:
        self.results = results

    def execute(self, **kwargs: Any) -> RevocationDispatchResult:
        del kwargs
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def confirmed_external_handler(**kwargs: Any) -> RevocationDispatchResult:
    operation_id = kwargs["operation_id"]
    return RevocationDispatchResult(
        destination_key="external_processor",
        succeeded=True,
        confirmation_reference=f"external-confirmation:{operation_id}",
    )


def test_dispatch_attempt_history_is_append_only_evidenced_and_audited(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked
    )
    adapter = SequencedRevocationAdapter(
        [
            RuntimeError("synthetic transport failure"),
            RevocationDispatchResult(
                destination_key="clinic_operations",
                succeeded=True,
                confirmation_reference="processor-confirmation-001",
            ),
        ]
    )
    monkeypatch.setattr(
        consent_services,
        "REVOCATION_ADAPTER_REGISTRY",
        {"clinic_operations": adapter},
    )

    failed = process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
    confirmed = process_revocation_dispatch(
        clinic_id=clinic.pk,
        dispatch_id=dispatch.pk,
    )

    attempt_model = consent_models.ConsentRevocationDispatchAttempt
    attempts = list(
        attempt_model.objects.for_clinic(clinic.pk)
        .filter(dispatch=dispatch)
        .order_by("attempt_number")
    )
    assert failed.status == ConsentRevocationDispatch.Status.FAILED
    assert confirmed.status == ConsentRevocationDispatch.Status.CONFIRMED
    assert [attempt.outcome for attempt in attempts] == ["failed", "confirmed"]
    assert all(attempt.evidence_digest for attempt in attempts)
    assert attempts[0].evidence_digest != attempts[1].evidence_digest
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            resource_type="consent_revocation_dispatch_attempt",
            resource_id__in=[str(attempt.pk) for attempt in attempts],
        ).count()
        == 2
    )
    with pytest.raises(PermissionDenied):
        attempt_model.objects.for_clinic(clinic.pk).filter(pk=attempts[0].pk).update(
            evidence_digest="0" * 64
        )
    with pytest.raises(PermissionDenied):
        attempts[0].delete()


def test_dispatch_rejects_empty_success_evidence_and_protects_obligation(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked
    )
    adapter = SequencedRevocationAdapter(
        [
            RevocationDispatchResult(
                destination_key="clinic_operations",
                succeeded=True,
                confirmation_reference="   ",
            )
        ]
    )
    monkeypatch.setattr(
        consent_services,
        "REVOCATION_ADAPTER_REGISTRY",
        {"clinic_operations": adapter},
    )

    processed = process_revocation_dispatch(
        clinic_id=clinic.pk,
        dispatch_id=dispatch.pk,
    )

    assert processed.status == ConsentRevocationDispatch.Status.FAILED
    assert not processed.confirmed_at
    with pytest.raises(PermissionDenied):
        ConsentRevocationDispatch.objects.for_clinic(clinic.pk).filter(
            pk=dispatch.pk
        ).update(status=ConsentRevocationDispatch.Status.CONFIRMED)
    dispatch.destination = "tampered-destination"
    with pytest.raises(PermissionDenied):
        dispatch.save()
    with pytest.raises(PermissionDenied):
        dispatch.delete()


def test_pending_revocation_dispatches_have_an_operational_command(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked
    )
    output = StringIO()

    with pytest.raises(CommandError):
        call_command(
            "process_revocation_dispatches",
            "--clinic-id",
            str(clinic.pk),
            stdout=output,
        )
    work_item = consent_models.ConsentRevocationWorkItem.objects.for_clinic(
        clinic.pk
    ).get(dispatch=dispatch)
    consent_services.acknowledge_revocation_work_item(
        clinic_id=clinic.pk,
        actor=administrator,
        work_item_id=work_item.pk,
        acknowledgement_reference="ticket-operacional-command-001",
    )
    success_output = StringIO()

    call_command(
        "process_revocation_dispatches",
        "--clinic-id",
        str(clinic.pk),
        stdout=success_output,
    )

    dispatch.refresh_from_db()
    assert dispatch.status == ConsentRevocationDispatch.Status.CONFIRMED
    assert "Confirmados: 1" in success_output.getvalue()
    assert "Falhos: 0" in success_output.getvalue()


@override_settings(
    CONSENT_REVOCATION_DESTINATIONS=("external_processor",),
    CONSENT_REVOCATION_HANDLERS={},
    CONSENT_REVOCATION_OVERDUE_SECONDS=0,
)
def test_dispatch_command_fails_visibly_and_exposes_overdue_obligations(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="external_processor",
    )
    output = StringIO()

    with pytest.raises(CommandError, match="despacho"):
        call_command(
            "process_revocation_dispatches",
            "--clinic-id",
            str(clinic.pk),
            stdout=output,
        )

    dispatch.refresh_from_db()
    assert dispatch.status == ConsentRevocationDispatch.Status.FAILED
    assert "Confirmados: 0" in output.getvalue()
    assert "Falhos: 1" in output.getvalue()
    assert "Obrigações vencidas: 1" in output.getvalue()


@override_settings(
    CONSENT_REVOCATION_DESTINATIONS=("external_processor",),
    CONSENT_REVOCATION_HANDLERS={},
)
def test_dispatch_command_retries_failed_obligations_by_default(client: Client) -> None:
    patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked,
        destination="external_processor",
    )
    first = process_revocation_dispatch(clinic_id=clinic.pk, dispatch_id=dispatch.pk)
    assert first.status == ConsentRevocationDispatch.Status.FAILED

    with override_settings(
        CONSENT_REVOCATION_HANDLERS={
            "external_processor": confirmed_external_handler,
        }
    ):
        output = StringIO()
        call_command(
            "process_revocation_dispatches",
            "--clinic-id",
            str(clinic.pk),
            stdout=output,
        )

    dispatch.refresh_from_db()
    assert dispatch.status == ConsentRevocationDispatch.Status.CONFIRMED
    assert "Confirmados: 1" in output.getvalue()
    assert "Falhos: 0" in output.getvalue()


@override_settings(
    CONSENT_REVOCATION_DESTINATIONS=("external_processor",),
    CONSENT_REVOCATION_HANDLERS={},
)
def test_dispatch_command_limit_does_not_hide_failed_obligations(
    client: Client,
) -> None:
    first_patient, clinic = patient_context(client)
    _administrator, document = published_optional_document(clinic=clinic)
    accepted_revocation(
        patient=first_patient,
        clinic=clinic,
        document=document,
    )
    second_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=second_patient,
        role=ClinicMembership.Role.PATIENT,
    )
    second_revocation = accepted_revocation(
        patient=second_patient,
        clinic=clinic,
        document=document,
    )
    failed_dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=second_revocation,
        destination="external_processor",
    )
    failed_dispatch = process_revocation_dispatch(
        clinic_id=clinic.pk,
        dispatch_id=failed_dispatch.pk,
    )
    assert failed_dispatch.status == ConsentRevocationDispatch.Status.FAILED
    output = StringIO()

    with (
        override_settings(
            CONSENT_REVOCATION_HANDLERS={
                "external_processor": confirmed_external_handler,
            }
        ),
        pytest.raises(CommandError, match="despacho"),
    ):
        call_command(
            "process_revocation_dispatches",
            "--clinic-id",
            str(clinic.pk),
            "--limit",
            "1",
            stdout=output,
        )

    assert "Falhas remanescentes: 1" in output.getvalue()


@override_settings(
    CONSENT_REVOCATION_DESTINATIONS=("clinic_operations", "external_processor")
)
def test_revocation_creates_one_obligation_per_configured_destination(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)

    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)

    assert set(
        ConsentRevocationDispatch.objects.for_clinic(clinic.pk)
        .filter(manifestation=revoked)
        .values_list("destination", flat=True)
    ) == {"clinic_operations", "external_processor"}


def test_dispatch_processing_denies_cross_tenant_identifiers(client: Client) -> None:
    patient, clinic = patient_context(client)
    _, document = published_optional_document(clinic=clinic)
    revoked = accepted_revocation(patient=patient, clinic=clinic, document=document)
    dispatch = ConsentRevocationDispatch.infrastructure_objects.get(
        manifestation=revoked
    )
    other_clinic = ClinicFactory.create()

    with pytest.raises(ValidationError, match="indisponível"):
        process_revocation_dispatch(
            clinic_id=other_clinic.pk,
            dispatch_id=dispatch.pk,
        )

    attempt_model = consent_models.ConsentRevocationDispatchAttempt
    assert not attempt_model.infrastructure_objects.filter(dispatch=dispatch).exists()


@pytest.mark.parametrize(
    ("party", "membership_overrides"),
    (
        ("representative", {"is_active": False}),
        (
            "represented_subject",
            {
                "valid_from": date.today() - timedelta(days=2),
                "valid_until": date.today() - timedelta(days=1),
            },
        ),
    ),
)
def test_representation_requires_active_memberships_for_both_parties(
    client: Client,
    party: str,
    membership_overrides: dict[str, object],
) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    representative_membership = ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    target_membership = (
        representative_membership
        if party == "representative"
        else ClinicMembership.infrastructure_objects.get(
            clinic=clinic,
            user=patient,
        )
    )
    for field, value in membership_overrides.items():
        setattr(target_membership, field, value)
    target_membership.save(update_fields=tuple(membership_overrides))

    with pytest.raises(PermissionDenied, match="vínculo ativo"):
        register_legal_representation(
            clinic_id=clinic.pk,
            actor=administrator,
            representative_id=representative.pk,
            represented_subject_id=patient.pk,
            relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
            granted_purposes=("communication",),
            evidence_reference="synthetic-inactive-party-evidence",
            valid_from=timezone.localdate(),
            valid_until=timezone.localdate() + timedelta(days=90),
            next_review_at=timezone.localdate() + timedelta(days=30),
        )


def test_access_review_suspends_links_with_inconsistent_party_memberships(
    client: Client,
) -> None:
    _patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    expected_reasons: dict[object, str] = {}
    scenarios: tuple[tuple[dict[str, object], dict[str, object], str], ...] = (
        ({"is_active": False}, {}, "therapist_membership_inactive"),
        (
            {
                "valid_from": timezone.localdate() - timedelta(days=2),
                "valid_until": timezone.localdate() - timedelta(days=1),
            },
            {},
            "therapist_membership_inactive",
        ),
        (
            {"role": ClinicMembership.Role.ADMINISTRATIVE_STAFF},
            {},
            "therapist_membership_not_therapist",
        ),
        ({}, {"is_active": False}, "patient_membership_inactive"),
    )
    for therapist_changes, patient_changes, reason in scenarios:
        therapist = UserFactory.create()
        patient = UserFactory.create()
        ClinicMembershipFactory.create(
            clinic=clinic,
            user=therapist,
            **{
                "role": ClinicMembership.Role.THERAPIST,
                **therapist_changes,
            },
        )
        ClinicMembershipFactory.create(
            clinic=clinic,
            user=patient,
            role=ClinicMembership.Role.PATIENT,
            **patient_changes,
        )
        relationship = CareRelationship.infrastructure_objects.create(
            clinic=clinic,
            therapist=therapist,
            patient=patient,
            valid_from=timezone.localdate(),
        )
        expected_reasons[relationship.pk] = reason

    report = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    relationship_exceptions = {
        item.resource_id: item.reason
        for item in report.exceptions
        if item.resource_type == "care_relationship"
    }
    assert relationship_exceptions == expected_reasons
    assert not CareRelationship.infrastructure_objects.filter(
        pk__in=expected_reasons,
        is_active=True,
    ).exists()


def test_access_review_runs_and_exceptions_are_persisted_idempotently_and_resolved(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    membership = ClinicMembership.infrastructure_objects.get(
        clinic=clinic,
        user=patient,
    )
    membership.valid_from = timezone.localdate() - timedelta(days=2)
    membership.valid_until = timezone.localdate() - timedelta(days=1)
    membership.save(update_fields=("valid_from", "valid_until"))

    first = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)
    repeated = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)
    next_date = timezone.localdate() + timedelta(days=1)
    monkeypatch.setattr(
        "consents.services.timezone.localdate",
        lambda: next_date,
    )
    later = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    run_model = consent_models.AccessReviewRun
    exception_model = consent_models.AccessReviewException
    assert first.run_id == repeated.run_id
    assert later.run_id != first.run_id
    assert run_model.objects.for_clinic(clinic.pk).count() == 2
    assert exception_model.objects.for_clinic(clinic.pk).count() == 1
    exception = exception_model.objects.for_clinic(clinic.pk).get()
    with pytest.raises(ValidationError, match="evidência"):
        consent_services.resolve_access_review_exception(
            clinic_id=clinic.pk,
            actor=administrator,
            exception_id=exception.pk,
            resolution_reference=" ",
        )
    resolved = consent_services.resolve_access_review_exception(
        clinic_id=clinic.pk,
        actor=administrator,
        exception_id=exception.pk,
        resolution_reference="ticket-operacional-001",
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_digest
    assert AuditEvent.infrastructure_objects.filter(
        clinic_id=clinic.pk,
        actor_id=administrator.pk,
        action=AuditAction.PERMISSION_CHANGE,
        resource_type="access_review_exception",
        resource_id=str(exception.pk),
        outcome=AuditOutcome.SUCCESS,
    ).exists()


def test_resolved_access_review_exception_reopens_when_condition_recurs(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(
        clinic=clinic,
        effective_until=timezone.now() + timedelta(days=1),
    )
    accepted = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    base_time = timezone.now()
    monkeypatch.setattr(
        "consents.services.timezone.now",
        lambda: base_time + timedelta(days=2),
    )
    monkeypatch.setattr(
        "consents.services.timezone.localdate",
        lambda: (base_time + timedelta(days=2)).date(),
    )
    first = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)
    exception = consent_models.AccessReviewException.objects.for_clinic(clinic.pk).get(
        last_seen_run_id=first.run_id,
        resource_type="consent_manifestation",
        resource_id=accepted.pk,
    )
    resolved = consent_services.resolve_access_review_exception(
        clinic_id=clinic.pk,
        actor=administrator,
        exception_id=exception.pk,
        resolution_reference="ticket-operacional-resolvido-001",
    )
    prior_resolution = (
        resolved.resolved_at,
        resolved.resolved_by_id,
        resolved.resolution_digest,
    )
    monkeypatch.setattr(
        "consents.services.timezone.now",
        lambda: base_time + timedelta(days=3),
    )
    monkeypatch.setattr(
        "consents.services.timezone.localdate",
        lambda: (base_time + timedelta(days=3)).date(),
    )

    later = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    exception.refresh_from_db()
    assert later.run_id != first.run_id
    assert exception.status == consent_models.AccessReviewException.Status.OPEN
    assert exception.last_seen_run_id == later.run_id
    assert (
        exception.resolved_at,
        exception.resolved_by_id,
        exception.resolution_digest,
    ) == prior_resolution
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            actor_id=administrator.pk,
            action=AuditAction.PERMISSION_CHANGE,
            resource_type="access_review_exception",
            resource_id=str(exception.pk),
            outcome=AuditOutcome.SUCCESS,
        ).count()
        == 2
    )


@pytest.mark.django_db(transaction=True)
def test_access_review_is_race_idempotent_on_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("A prova de bloqueio concorrente exige PostgreSQL.")
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    original_lock = lock_clinic_for_update
    first_lock_barrier = Barrier(2)
    thread_state = local()

    def synchronized_lock(*, clinic_id: UUID) -> None:
        if not getattr(thread_state, "synchronized", False):
            thread_state.synchronized = True
            first_lock_barrier.wait(timeout=10)
        original_lock(clinic_id=clinic_id)

    monkeypatch.setattr(
        consent_services,
        "lock_clinic_for_update",
        synchronized_lock,
    )

    def perform_review() -> object:
        close_old_connections()
        try:
            actor = User.objects.get(pk=administrator.pk)
            return review_access_lifecycle(clinic_id=clinic.pk, actor=actor).run_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(perform_review) for _index in range(2)]
        try:
            run_ids = [future.result(timeout=20) for future in futures]
        except Exception as exc:  # noqa: BLE001 - convert race errors to assertion
            pytest.fail(f"A revisão concorrente falhou: {exc!r}")

    assert run_ids[0] == run_ids[1]
    assert consent_models.AccessReviewRun.objects.for_clinic(clinic.pk).count() == 1


def test_access_review_has_an_authorized_operational_command(client: Client) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    membership = ClinicMembership.infrastructure_objects.get(
        clinic=clinic,
        user=patient,
    )
    membership.valid_from = timezone.localdate() - timedelta(days=2)
    membership.valid_until = timezone.localdate() - timedelta(days=1)
    membership.save(update_fields=("valid_from", "valid_until"))
    output = StringIO()

    call_command(
        "review_access_lifecycle",
        "--clinic-id",
        str(clinic.pk),
        "--actor-id",
        str(administrator.pk),
        stdout=output,
    )

    run_model = consent_models.AccessReviewRun
    assert run_model.objects.for_clinic(clinic.pk).count() == 1
    assert "1 exceção" in output.getvalue()


def test_expired_consent_exception_is_not_duplicated_across_review_dates(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient, clinic = patient_context(client)
    administrator, document = published_optional_document(
        clinic=clinic,
        effective_until=timezone.now() + timedelta(days=1),
    )
    accepted = record_consent_manifestation(
        clinic_id=clinic.pk,
        actor=patient,
        subject_id=patient.pk,
        document_id=document.pk,
        decision=ConsentManifestation.Decision.ACCEPTED,
        request_id=uuid4(),
    )
    base_time = timezone.now()
    monkeypatch.setattr(
        "consents.services.timezone.now",
        lambda: base_time + timedelta(days=2),
    )

    first = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)
    monkeypatch.setattr(
        "consents.services.timezone.now",
        lambda: base_time + timedelta(days=3),
    )
    later = review_access_lifecycle(clinic_id=clinic.pk, actor=administrator)

    exception_model = consent_models.AccessReviewException
    assert first.run_id != later.run_id
    assert (
        exception_model.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="consent_manifestation",
            resource_id=accepted.pk,
            reason="consent_document_expired",
        )
        .count()
        == 1
    )
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            action=AuditAction.PERMISSION_CHANGE,
            resource_type="consent_manifestation",
            resource_id=str(accepted.pk),
        ).count()
        == 1
    )


def test_legal_representation_is_immutable_except_for_audited_lifecycle_service(
    client: Client,
) -> None:
    patient, clinic = patient_context(client)
    administrator, _ = published_optional_document(clinic=clinic)
    representative = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=representative,
        role=ClinicMembership.Role.PATIENT,
    )
    representation = register_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representative_id=representative.pk,
        represented_subject_id=patient.pk,
        relationship_type=LegalRepresentation.RelationshipType.LEGAL_GUARDIAN,
        granted_purposes=("communication",),
        evidence_reference="synthetic-immutable-representation",
        valid_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=90),
        next_review_at=timezone.localdate() + timedelta(days=30),
    )

    representation.granted_purposes = ["clinical_follow_up"]
    with pytest.raises(PermissionDenied):
        representation.save()
    with pytest.raises(PermissionDenied):
        LegalRepresentation.objects.for_clinic(clinic.pk).filter(
            pk=representation.pk
        ).update(evidence_digest="0" * 64)
    with pytest.raises(PermissionDenied):
        representation.delete()

    transitioned = consent_services.transition_legal_representation(
        clinic_id=clinic.pk,
        actor=administrator,
        representation_id=representation.pk,
        status=LegalRepresentation.Status.SUSPENDED,
        reason="Revisão administrativa necessária.",
    )

    assert transitioned.status == LegalRepresentation.Status.SUSPENDED
    assert (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=clinic.pk,
            actor_id=administrator.pk,
            action=AuditAction.PERMISSION_CHANGE,
            resource_type="legal_representation",
            resource_id=str(representation.pk),
            outcome=AuditOutcome.SUCCESS,
        ).count()
        >= 2
    )
