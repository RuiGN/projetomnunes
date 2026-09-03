"""Round-2 review fix wave: PRD 8.12.4 credential governance tests.

Covers Critical C1 and Important findings I1-I4 from
.superpowers/sdd/task-8.12.4-review-round2.md.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _clinic_with_admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=admin,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, admin


def _therapist(clinic: Clinic, *, verified: bool) -> User:
    from people.models import ProfessionalCredential, ProfessionalProfile

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
    ProfessionalCredential.objects.create(profile=profile)
    if verified:
        profile.credential.status = ProfessionalCredential.Status.VERIFIED
        profile.credential.council_name = "CRP"
        profile.credential.council_number = "123456"
        profile.credential.council_jurisdiction = "PE"
        profile.credential.save()
    return therapist


def _patient(clinic: Clinic) -> User:
    patient = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=patient, role=ClinicMembership.Role.PATIENT
    )
    return patient


def _published_content(
    clinic: Clinic,
    author: User,
    slug: str,
    *,
    valid_until: date | None = None,
) -> content_models.Content:
    from content.models import Content, ContentKind, ContentStatus

    return Content.infrastructure_objects.create(
        clinic=clinic,
        slug=slug,
        title=slug,
        kind=ContentKind.ARTICLE,
        status=ContentStatus.PUBLISHED,
        created_by=author,
        valid_until=valid_until,
    )


def _reviewed_content(
    clinic: Clinic,
    *,
    submitter: User,
    approver: User,
    slug: str,
) -> tuple[content_models.Content, content_models.ContentVersion]:
    from content.models import Content, ContentKind

    content = Content.infrastructure_objects.create(
        clinic=clinic,
        slug=slug,
        title=slug,
        kind=ContentKind.ARTICLE,
        created_by=submitter,
    )
    version = content_services.create_content_version(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        body="<p>Conteúdo clínico revisado.</p>",
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    content_services.approve_content_version(
        clinic_id=clinic.pk,
        actor=approver,
        content_id=content.pk,
        opinion="Parecer favorável: conteúdo consistente com boas práticas.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    return content, version


def _workflow_clinic() -> tuple[Clinic, User, User, User]:
    """Return clinic, verified editorial admin and second verified therapist."""
    clinic, admin = _clinic_with_admin()
    submitter = _therapist(clinic, verified=True)
    approver = _therapist(clinic, verified=True)
    # grant the second therapist admin role for editorial management actions
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=submitter,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, admin, submitter, approver


# ---------------------------------------------------------------------------
# Critical C1 — credential gating
# ---------------------------------------------------------------------------


def test_approval_requires_verified_professional_credential() -> None:
    clinic, admin = _clinic_with_admin()
    from people.models import ProfessionalCredential, ProfessionalProfile

    submitter = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=submitter,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    profile = ProfessionalProfile.infrastructure_objects.create(
        clinic=clinic,
        user=submitter,
        full_name="Dra. Submetedora",
        professional_email=submitter.email,
        category="psychologist",
    )
    ProfessionalCredential.objects.create(
        profile=profile, status=ProfessionalCredential.Status.VERIFIED
    )
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug="gate",
        title="Gate de credencial",
        kind=content_models.ContentKind.ARTICLE,
        body="<p>Conteúdo clínico.</p>",
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    # admin without professional profile cannot approve
    with pytest.raises(PermissionDenied):
        content_services.approve_content_version(
            clinic_id=clinic.pk,
            actor=admin,
            content_id=content.pk,
            opinion="Parecer.",
            request_id=uuid4(),
        )


def test_recommendation_requires_verified_credential() -> None:
    clinic, _admin = _clinic_with_admin()
    unverified = _therapist(clinic, verified=False)
    therapist = _therapist(clinic, verified=True)
    content = _published_content(clinic, therapist, "recomendavel")
    patient = _patient(clinic)
    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=unverified,
            content_id=content.pk,
            patient_id=patient.pk,
            cohort_id=None,
            objective="Apoio entre sessões",
            priority="normal",
            context="Complemento do plano de cuidado.",
            request_id=uuid4(),
        )


def test_recommendation_with_verified_credential_persists_snapshot() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)
    content = _published_content(clinic, therapist, "com-snapshot")
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Reforço do plano.",
        priority="high",
        context="Continuidade do cuidado.",
        valid_days=14,
        request_id=uuid4(),
    )
    assert recommendation.credential_snapshot["council_number"] == "123456"
    assert recommendation.credential_digest
    assert recommendation.priority == "high"


# ---------------------------------------------------------------------------
# Important I2 — visibility and cascade retirement
# ---------------------------------------------------------------------------


def test_recommendations_for_patient_excludes_expired_and_archived() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)

    active_content = _published_content(clinic, therapist, "conteudo-ativo")
    archived_content = _published_content(clinic, therapist, "conteudo-arquivado")
    content_services.archive_content(
        clinic_id=clinic.pk,
        actor=admin,
        content_id=archived_content.pk,
        request_id=uuid4(),
    )

    content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=active_content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Ativa",
        priority="normal",
        context="Plano vigente.",
        valid_days=30,
        request_id=uuid4(),
    )
    expired = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=active_content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Vencida",
        priority="low",
        context="Janela encerrada.",
        valid_days=1,
        request_id=uuid4(),
    )
    expired.valid_until = timezone.localdate() - timedelta(days=1)
    expired.save()

    listing = content_services.recommendations_for_patient(
        clinic_id=clinic.pk, user=patient
    )
    objectives = [row["objective"] for row in listing]
    assert "Ativa" in objectives
    assert "Vencida" not in objectives
    assert not any(row["content_slug"] == "conteudo-arquivado" for row in listing)


def test_archive_content_retires_recommendations_and_notifies() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)
    content = _published_content(clinic, therapist, "sera-arquivado")
    content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Sera retirada",
        priority="normal",
        context="Cascata.",
        valid_days=30,
        request_id=uuid4(),
    )

    content_services.archive_content(
        clinic_id=clinic.pk, actor=admin, content_id=content.pk, request_id=uuid4()
    )
    from content.models import ContentNotification, ContentRecommendation

    row = ContentRecommendation.infrastructure_objects.get(content=content)
    assert row.status == "retired"
    assert row.retired_reason == "content_archived"
    assert ContentNotification.infrastructure_objects.filter(
        clinic_id=clinic.pk, recipient_id=patient.pk
    ).exists()


def test_retirement_notifies_affected_patient() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)
    content = _published_content(clinic, therapist, "retirada-direta")
    recommendation = content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Direta",
        priority="normal",
        context="Notificacao.",
        valid_days=30,
        request_id=uuid4(),
    )
    content_services.retire_recommendation(
        clinic_id=clinic.pk,
        actor=admin,
        recommendation_id=recommendation.pk,
        reason="Reavaliação clínica",
        request_id=uuid4(),
    )
    from content.models import ContentNotification

    assert ContentNotification.infrastructure_objects.filter(
        clinic_id=clinic.pk, recipient_id=patient.pk, recommendation=recommendation
    ).exists()


# ---------------------------------------------------------------------------
# Important I3 — patient attribution shows display name, never email
# ---------------------------------------------------------------------------


def test_patient_listing_shows_professional_name_not_email() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)
    content = _published_content(clinic, therapist, "atribuicao")
    content_services.recommend_content(
        clinic_id=clinic.pk,
        actor=therapist,
        content_id=content.pk,
        patient_id=patient.pk,
        cohort_id=None,
        objective="Visivel",
        priority="normal",
        context="Atribuicao clara.",
        valid_days=30,
        request_id=uuid4(),
    )
    listing = content_services.recommendations_for_patient(
        clinic_id=clinic.pk, user=patient
    )
    assert listing[0]["recommended_by"] == "Dra. Ana Terapeuta"
    assert "@" not in str(listing[0]["recommended_by"])


# ---------------------------------------------------------------------------
# Minor findings
# ---------------------------------------------------------------------------


def test_recommendation_targets_patient_role_membership_only() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    other_admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=other_admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    content = _published_content(clinic, therapist, "alvo-errado")
    with pytest.raises(PermissionDenied):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=content.pk,
            patient_id=other_admin.pk,
            cohort_id=None,
            objective="Errado",
            priority="normal",
            context="Deve negar.",
            request_id=uuid4(),
        )


def test_recommendation_requires_target_and_positive_validity() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    content = _published_content(clinic, therapist, "sem-alvo")
    with pytest.raises(ValidationError):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=content.pk,
            patient_id=None,
            cohort_id=None,
            objective="Sem alvo",
            priority="normal",
            context="Deve negar.",
            request_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=content.pk,
            patient_id=None,
            cohort_id=None,
            objective="Invalido",
            priority="normal",
            context="Deve negar.",
            valid_days=0,
            request_id=uuid4(),
        )


def test_recommendation_rejects_expired_content() -> None:
    clinic, admin = _clinic_with_admin()
    therapist = _therapist(clinic, verified=True)
    patient = _patient(clinic)
    content = _published_content(
        clinic,
        therapist,
        "conteudo-vencido",
        valid_until=(timezone.localdate() - timedelta(days=2)),
    )
    with pytest.raises(ValidationError):
        content_services.recommend_content(
            clinic_id=clinic.pk,
            actor=therapist,
            content_id=content.pk,
            patient_id=patient.pk,
            cohort_id=None,
            objective="Vencido",
            priority="normal",
            context="Deve negar.",
            request_id=uuid4(),
        )
