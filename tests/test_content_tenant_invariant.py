"""Round-2 review fix wave: PRD 8.12.1 I-1 DB-enforced same-tenant invariant.

Regression tests prove the database itself rejects cross-tenant references
inside the content tree (Content -> ContentVersion / ContentMedia), even when
rows are created through infrastructure_objects, bypassing services.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, ProgrammingError, transaction

import content.models as content_models
from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db

# The same-tenant invariant is enforced by a database trigger. SQLite's
# RAISE(ABORT) surfaces as IntegrityError; PostgreSQL's plpgsql RAISE EXCEPTION
# surfaces as ProgrammingError. Both prove the write was rejected.
_TENANT_VIOLATION = (IntegrityError, ProgrammingError)


def _two_clinic_setup() -> tuple[Clinic, Clinic, User]:
    clinic_a = ClinicFactory.create()
    clinic_b = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic_a, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic_b, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic_a, clinic_b, admin


def test_cross_tenant_content_version_is_rejected_by_database() -> None:
    clinic_a, clinic_b, admin = _two_clinic_setup()
    content = content_models.Content.infrastructure_objects.create(
        clinic=clinic_a,
        slug="raiz-a",
        title="Raiz A",
        kind=content_models.ContentKind.ARTICLE,
        created_by=admin,
    )
    with pytest.raises(_TENANT_VIOLATION), transaction.atomic():
        content_models.ContentVersion.infrastructure_objects.create(
            clinic=clinic_b,  # tenant mismatch: parent belongs to clinic_a
            content_id=content.pk,
            version=1,
            body="<p>corpo</p>",
            status=content_models.ContentStatus.DRAFT,
        )


def test_cross_tenant_content_media_is_rejected_by_database() -> None:
    clinic_a, clinic_b, admin = _two_clinic_setup()
    content = content_models.Content.infrastructure_objects.create(
        clinic=clinic_a,
        slug="raiz-media",
        title="Raiz media",
        kind=content_models.ContentKind.ARTICLE,
        created_by=admin,
    )
    with pytest.raises(_TENANT_VIOLATION), transaction.atomic():
        content_models.ContentMedia.infrastructure_objects.create(
            clinic=clinic_b,  # tenant mismatch: parent belongs to clinic_a
            content_id=content.pk,
            original_name="arquivo.png",
            content_type="image/png",
            file="content/media/teste.png",
        )


def test_tenant_move_of_content_row_is_rejected_by_database() -> None:
    clinic_a, clinic_b, admin = _two_clinic_setup()
    content = content_models.Content.infrastructure_objects.create(
        clinic=clinic_a,
        slug="imutavel",
        title="Imutável",
        kind=content_models.ContentKind.ARTICLE,
        created_by=admin,
    )
    with pytest.raises(_TENANT_VIOLATION), transaction.atomic():
        content_models.Content.infrastructure_objects.filter(pk=content.pk).update(
            clinic_id=clinic_b.pk
        )


def test_same_tenant_writes_continue_to_work() -> None:
    clinic_a, _clinic_b, admin = _two_clinic_setup()
    content = content_models.Content.infrastructure_objects.create(
        clinic=clinic_a,
        slug="legitimo",
        title="Legítimo",
        kind=content_models.ContentKind.ARTICLE,
        created_by=admin,
    )
    version = content_models.ContentVersion.infrastructure_objects.create(
        clinic=clinic_a,
        content_id=content.pk,
        version=1,
        body="<p>corpo</p>",
        status=content_models.ContentStatus.DRAFT,
    )
    assert version.clinic_id == clinic_a.pk
