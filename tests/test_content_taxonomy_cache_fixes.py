"""Round-2 review fix wave: PRD 8.12.1 cache invalidation + managed taxonomy.

Covers Important I-3 (managed taxonomy) and I-4 (cache invalidation) from
.superpowers/sdd/task-8.12.1-review-round2.md.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import content.models as content_models
import content.services as content_services
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _governed_clinic() -> tuple[Clinic, User, User, User]:
    from people.models import ProfessionalCredential, ProfessionalProfile

    clinic = ClinicFactory.create()
    submitter = UserFactory.create()
    reviewer = UserFactory.create()
    publisher = UserFactory.create()
    for user in (submitter, reviewer, publisher):
        ClinicMembershipFactory.create(
            clinic=clinic, user=user, role=ClinicMembership.Role.CLINIC_ADMIN
        )
    for professional in (reviewer, publisher):
        profile = ProfessionalProfile.infrastructure_objects.create(
            clinic=clinic,
            user=professional,
            full_name=f"Prof. {professional.pk}",
            professional_email=professional.email,
            category="psychologist",
        )
        credential = ProfessionalCredential.objects.create(profile=profile)
        credential.status = ProfessionalCredential.Status.VERIFIED
        credential.council_name = "CRP"
        credential.council_number = uuid4().hex[:6]
        credential.council_jurisdiction = "PE"
        credential.save()
    return clinic, submitter, reviewer, publisher


def _publish(
    clinic: Clinic,
    submitter: User,
    reviewer: User,
    publisher: User,
    slug: str,
) -> content_models.Content:
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug=slug,
        title=f"Conteúdo {slug}",
        kind=content_models.ContentKind.ARTICLE,
        body="<p>Texto clínico revisado.</p>",
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
    return content_services.publish_content_version(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )


# ---------------------------------------------------------------------------
# I-4 — cache invalidation on publish/rollback/archive
# ---------------------------------------------------------------------------


def test_publish_invalidates_published_content_cache() -> None:
    clinic, submitter, reviewer, publisher = _governed_clinic()
    # Warm the cache with a search that sees zero published items.
    first = content_services.search_published_content(
        clinic_id=clinic.pk, query="conteúdo"
    )
    assert first == []

    _publish(clinic, submitter, reviewer, publisher, "invalidacao-cache")

    second = content_services.search_published_content(
        clinic_id=clinic.pk, query="conteúdo"
    )
    assert len(second) == 1


def test_archive_invalidates_published_content_cache() -> None:
    clinic, submitter, reviewer, publisher = _governed_clinic()
    content = _publish(clinic, submitter, reviewer, publisher, "arquivavel")
    assert (
        len(
            content_services.search_published_content(
                clinic_id=clinic.pk, query="arquivavel"
            )
        )
        == 1
    )

    content_services.archive_content(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )
    assert (
        content_services.search_published_content(
            clinic_id=clinic.pk, query="arquivavel"
        )
        == []
    )


def test_rollback_invalidates_published_content_cache() -> None:
    clinic, submitter, reviewer, publisher = _governed_clinic()
    content = _publish(clinic, submitter, reviewer, publisher, "rollback-cache")
    first_version = content.current_version
    content_services.create_content_version(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        body="<p>Segunda redação diferente.</p>",
        request_id=uuid4(),
    )
    content_services.submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    content_services.approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer da segunda versão.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    content_services.publish_content_version(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )
    assert (
        len(
            content_services.search_published_content(
                clinic_id=clinic.pk, query="redação"
            )
        )
        == 1
    )

    content_services.rollback_content(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        target_version=first_version,
        request_id=uuid4(),
    )
    # v1 body is back in the searchable index; v2 text is gone.
    assert (
        content_services.search_published_content(clinic_id=clinic.pk, query="redação")
        == []
    )
    assert (
        len(
            content_services.search_published_content(
                clinic_id=clinic.pk, query="conteúdo"
            )
        )
        == 1
    )


# ---------------------------------------------------------------------------
# I-3 — managed taxonomy records
# ---------------------------------------------------------------------------


def test_taxonomy_records_are_managed_per_tenant() -> None:
    clinic, submitter, _reviewer, publisher = _governed_clinic()
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug="taxonomia",
        title="Conteúdo categorizado",
        kind=content_models.ContentKind.ARTICLE,
        body="<p>Corpo.</p>",
        categories=["Ansiedade", "Sono"],
        tags=["respiracao", "mindfulness"],
        request_id=uuid4(),
    )
    from content.models import ContentCategory, ContentTag

    category_names = set(
        ContentCategory.infrastructure_objects.filter(
            clinic=clinic, content_items=content
        ).values_list("name", flat=True)
    )
    tag_names = set(
        ContentTag.infrastructure_objects.filter(
            clinic=clinic, content_items=content
        ).values_list("name", flat=True)
    )
    assert category_names == {"Ansiedade", "Sono"}
    assert tag_names == {"respiracao", "mindfulness"}

    # vocabulary is tenant-scoped and deduplicated
    category = ContentCategory.objects.for_clinic(clinic.pk).get(name="Ansiedade")
    assert category.clinic_id == clinic.pk

    # other tenants cannot see this vocabulary; attaching the same name creates
    # their own isolated record instead of crossing tenants
    other_clinic, _other_admin, _other_reviewer, _other_publisher = _governed_clinic()
    assert (
        ContentCategory.objects.for_clinic(other_clinic.pk)
        .filter(name="Ansiedade")
        .exists()
        is False
    )
    other_content = content_services.start_content(
        clinic_id=other_clinic.pk,
        actor=_other_admin,
        slug="outro-tenant",
        title="Outro",
        kind=content_models.ContentKind.ARTICLE,
        body="<p>Corpo.</p>",
        categories=["Ansiedade"],
        request_id=uuid4(),
    )
    assert (
        ContentCategory.infrastructure_objects.filter(
            clinic=other_clinic, content_items=other_content, name="Ansiedade"
        ).count()
        == 1
    )
    assert (
        ContentCategory.objects.for_clinic(other_clinic.pk).count() == 1
        and ContentCategory.objects.for_clinic(clinic.pk).count() == 2
    )


def _publish_with_taxonomy(
    clinic: Clinic,
    submitter: User,
    reviewer: User,
    publisher: User,
    slug: str,
    categories: list[str],
) -> content_models.Content:
    content = content_services.start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug=slug,
        title=f"Conteúdo {slug}",
        kind=content_models.ContentKind.ARTICLE,
        body="<p>Texto clínico revisado.</p>",
        categories=categories,
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
    return content_services.publish_content_version(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )


def test_search_filters_by_taxonomy() -> None:
    clinic, submitter, reviewer, publisher = _governed_clinic()
    _publish_with_taxonomy(
        clinic, submitter, reviewer, publisher, "com-categoria", ["Ansiedade"]
    )
    _publish_with_taxonomy(
        clinic, submitter, reviewer, publisher, "sem-categoria", ["Sono"]
    )
    results = content_services.search_published_content(
        clinic_id=clinic.pk, query="", category="Ansiedade"
    )
    assert [row.slug for row in results] == ["com-categoria"]
