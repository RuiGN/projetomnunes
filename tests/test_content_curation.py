"""Focused acceptance tests for PRD 8.12.4 clinical curation governance."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

import content.models as content_models
import content.services as content_services
import people.services as people_services
from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import ProfessionalCredential, ProfessionalProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _administrator() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, administrator


def _verified_therapist(clinic: Clinic) -> User:
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    profile = ProfessionalProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist,
        full_name="Dra. Ana Terapeuta",
        professional_email=therapist.email,
        category="psychologist",
    )
    credential = ProfessionalCredential.objects.create(profile=profile)
    credential.status = ProfessionalCredential.Status.VERIFIED
    credential.council_name = "CRP"
    credential.council_number = "123456"
    credential.council_jurisdiction = "PE"
    credential.save()
    return therapist


def _published_article(
    clinic: Clinic,
    submitter: User,
    reviewer: User,
    publisher: User,
    slug: str = "conteudo-clinico",
) -> content_models.Content:
    """Publish one article through the full governed editorial workflow."""
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug=slug,
        title="Orientações de respiração",
        kind=content_models.ContentKind.ARTICLE,
        body="Conteúdo educacional revisado.",
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        request_id=uuid4(),
    )
    content_services.approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável: conteúdo adequado ao público.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    return content_services.publish_content_version(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        request_id=uuid4(),
    )


def _verified_professional(clinic: Clinic, role: ClinicMembership.Role) -> User:
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=therapist, role=role)
    profile = ProfessionalProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist,
        full_name="Dra. Ana Terapeuta",
        professional_email=therapist.email,
        category="psychologist",
    )
    credential = ProfessionalCredential.objects.create(profile=profile)
    credential.status = ProfessionalCredential.Status.VERIFIED
    credential.council_name = "CRP"
    credential.council_number = "123456"
    credential.council_jurisdiction = "PE"
    credential.save()
    return therapist


def _governed_clinic() -> tuple[Clinic, User, User, User]:
    """Return clinic plus submitter/reviewer/publisher, all verified admins."""
    clinic, _ = _administrator()
    submitter = _verified_professional(clinic, ClinicMembership.Role.CLINIC_ADMIN)
    reviewer = _verified_professional(clinic, ClinicMembership.Role.CLINIC_ADMIN)
    publisher = _verified_professional(clinic, ClinicMembership.Role.CLINIC_ADMIN)
    return clinic, submitter, reviewer, publisher


def test_clinical_recommendation_requires_current_specialist_approval() -> None:
    """8.12.4.1/8.12.4.2 block clinical attribution without a valid parecer."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    verified_therapist = _verified_therapist(clinic)
    unverified = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=unverified, role=ClinicMembership.Role.THERAPIST
    )
    content = _published_article(clinic, submitter, reviewer, publisher)

    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            patient_id=None,
            cohort_id=None,
            objective="Apoio entre sessões",
            priority="normal",
            context="Complemento do plano de cuidado.",
            request_id=uuid4(),
        )
    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=unverified,
            content_id=content.pk,
            patient_id=None,
            cohort_id=None,
            objective="Apoio entre sessões",
            priority="normal",
            context="Complemento do plano de cuidado.",
            request_id=uuid4(),
        )

    cohort_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=cohort_patient, role=ClinicMembership.Role.PATIENT
    )
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=verified_therapist,
        content_id=content.pk,
        patient_id=cohort_patient.pk,
        cohort_id=None,
        objective="Apoio entre sessões",
        priority="normal",
        context="Complemento do plano de cuidado.",
        request_id=uuid4(),
    )
    assert recommendation.status == "active"
    assert recommendation.recommended_by_id == verified_therapist.pk
    assert recommendation.credential_snapshot["council_number"] == "123456"

    expired = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=verified_therapist,
        content_id=content.pk,
        patient_id=cohort_patient.pk,
        cohort_id=None,
        objective="Reavaliação",
        priority="normal",
        context="Janela curta de reavaliação.",
        valid_days=1,
        request_id=uuid4(),
    )
    assert expired.valid_until == timezone.localdate() + timedelta(days=1)


def test_clinical_recommendation_rejects_unpublished_content() -> None:
    """8.12.4.2 blocks attribution until the reviewed version is published."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    therapist = _verified_therapist(clinic)
    draft = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug="rascunho-clinico",
        title="Rascunho clínico",
        kind=content_models.ContentKind.ARTICLE,
        body="Ainda não revisado.",
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=draft.pk,
            patient_id=None,
            cohort_id=None,
            objective="Não pode ser atribuído",
            priority="normal",
            context="Deve falhar enquanto rascunho.",
            request_id=uuid4(),
        )


def test_revoked_or_expired_parcere_blocks_new_recommendations_and_audits() -> None:
    """8.12.4.2/8.12.4.4 retire recommendations with alerting and audit trail."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    therapist = _verified_therapist(clinic)
    target_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=target_patient, role=ClinicMembership.Role.PATIENT
    )
    content = _published_article(clinic, submitter, reviewer, publisher)
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=target_patient.pk,
        cohort_id=None,
        objective="Apoio entre sessões",
        priority="normal",
        context="Complemento do plano de cuidado.",
        request_id=uuid4(),
    )

    retired = content_services.retire_recommendation(
        clinic_id=clinic.pk,
        actor=publisher,
        recommendation_id=recommendation.pk,
        reason="Parecer clínico expirado",
        request_id=uuid4(),
    )
    assert retired.status == "retired"
    assert retired.retired_reason == "Parecer clínico expirado"
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="content_recommendation", resource_id=str(recommendation.pk)
        )
        .exists()
    )

    with pytest.raises(PermissionDenied):
        content_services.retire_recommendation(
            clinic_id=clinic.pk,
            actor=therapist,
            recommendation_id=recommendation.pk,
            reason="Tentativa sem permissão",
            request_id=uuid4(),
        )


def test_recommendation_requires_tenant_local_content_and_audits_creation() -> None:
    """8.12.4.3 fails closed against cross-tenant content attribution."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    other_clinic, _other_administrator = _administrator()
    other_submitter = _verified_professional(
        other_clinic, ClinicMembership.Role.CLINIC_ADMIN
    )
    other_reviewer = _verified_professional(
        other_clinic, ClinicMembership.Role.CLINIC_ADMIN
    )
    other_publisher = _verified_professional(
        other_clinic, ClinicMembership.Role.CLINIC_ADMIN
    )
    therapist = _verified_therapist(clinic)
    foreign_content = _published_article(
        other_clinic, other_submitter, other_reviewer, other_publisher
    )

    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=foreign_content.pk,
            patient_id=None,
            cohort_id=None,
            objective="Atribuição indevida",
            priority="normal",
            context="Deve falhar entre clínicas.",
            request_id=uuid4(),
        )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(resource_type="content_recommendation")
        .exists()
        is False
    )

    own_content = _published_article(
        clinic, submitter, reviewer, publisher, slug="conteudo-proprio"
    )
    own_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=own_patient, role=ClinicMembership.Role.PATIENT
    )
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=own_content.pk,
        patient_id=own_patient.pk,
        cohort_id=None,
        objective="Prática guiada",
        priority="normal",
        context="Continuidade do cuidado.",
        request_id=uuid4(),
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="content_recommendation", resource_id=str(recommendation.pk)
        )
        .exists()
    )


def test_patient_sees_recommendation_with_named_responsible_professional() -> None:
    """8.12.4.3 exposes the recommending professional without outcome promises."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    therapist = _verified_therapist(clinic)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    content = _published_article(clinic, submitter, reviewer, publisher)
    content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Apoio entre sessões",
        priority="normal",
        context="Complemento do plano de cuidado.",
        request_id=uuid4(),
    )

    listing = content_services.recommendations_for_patient(
        clinic_id=clinic.pk, user=patient
    )
    assert len(listing) == 1
    assert listing[0]["content_slug"] == "conteudo-clinico"
    assert listing[0]["recommended_by"] == "Dra. Ana Terapeuta"
    assert "@" not in str(listing[0]["recommended_by"])
    assert listing[0]["objective"] == "Apoio entre sessões"

    outsider = UserFactory.create()
    with pytest.raises(PermissionDenied):
        content_services.recommendations_for_patient(clinic_id=clinic.pk, user=outsider)


def test_revoking_credential_blocks_new_recommendations() -> None:
    """A revoked credential immediately stops new clinical attributions."""
    clinic, submitter, reviewer, publisher = _governed_clinic()
    therapist = _verified_therapist(clinic)
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    content = _published_article(clinic, submitter, reviewer, publisher)
    profile = ProfessionalProfile.infrastructure_objects.get(user_id=therapist.pk)

    people_services.revoke_professional_credential(
        clinic_id=clinic.pk,
        actor=publisher,
        profile_id=profile.pk,
        reason="Registro profissional inativo",
        request_id=uuid4(),
    )
    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=content.pk,
            patient_id=patient.pk,
            cohort_id=None,
            objective="Após revogação",
            priority="normal",
            context="Deve falhar com credencial revogada.",
            request_id=uuid4(),
        )


def test_revocation_cascades_retirement_of_active_recommendations() -> None:
    """Revoking a credential retires the professional's active recommendations."""
    from content.models import ContentNotification

    clinic, submitter, reviewer, publisher = _governed_clinic()
    therapist = _verified_therapist(clinic)
    target_patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=target_patient, role=ClinicMembership.Role.PATIENT
    )
    content = _published_article(clinic, submitter, reviewer, publisher)
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=target_patient.pk,
        cohort_id=None,
        objective="Apoio entre sessões",
        priority="normal",
        context="Complemento do plano de cuidado.",
        request_id=uuid4(),
    )
    profile = ProfessionalProfile.infrastructure_objects.get(user_id=therapist.pk)

    people_services.revoke_professional_credential(
        clinic_id=clinic.pk,
        actor=publisher,
        profile_id=profile.pk,
        reason="Registro profissional inativo",
        request_id=uuid4(),
    )

    recommendation.refresh_from_db()
    assert recommendation.status == "retired"
    assert recommendation.retired_reason == "credential_revoked"
    assert ContentNotification.infrastructure_objects.filter(
        clinic_id=clinic.pk, recipient_id=target_patient.pk
    ).exists()
    # patient listing no longer shows the retired recommendation
    listing = content_services.recommendations_for_patient(
        clinic_id=clinic.pk, user=target_patient
    )
    assert listing == []


def test_publish_blocks_when_approver_credential_is_revoked() -> None:
    """Publishing re-validates the approver's credential; revoked => blocked."""
    from uuid import uuid4

    clinic, submitter, reviewer, publisher = _governed_clinic()
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug="artigo-para-revogacao",
        title="Artigo sujeito a revogação",
        kind=content_models.ContentKind.ARTICLE,
        body="Conteúdo em revisão.",
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    content_services.approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    reviewer_profile = ProfessionalProfile.infrastructure_objects.get(
        user_id=reviewer.pk
    )
    people_services.revoke_professional_credential(
        clinic_id=clinic.pk,
        actor=publisher,
        profile_id=reviewer_profile.pk,
        reason="Registro suspenso",
        request_id=uuid4(),
    )
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        content_services.publish_content_version(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            request_id=uuid4(),
        )
