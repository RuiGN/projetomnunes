"""Acceptance tests for PRD 8.12.4.4 — periodic review, denúncia and substitution."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

import content.models as content_models
import content.services as content_services
from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def _patient(clinic: Clinic) -> User:
    user = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=user, role=ClinicMembership.Role.PATIENT
    )
    return user


def _published_content(
    clinic: Clinic, creator: User, slug: str
) -> content_models.Content:
    return content_models.Content.infrastructure_objects.create(
        clinic=clinic,
        slug=slug,
        title=slug,
        kind=content_models.ContentKind.ARTICLE,
        status=content_models.ContentStatus.PUBLISHED,
        current_version=1,
        created_by=creator,
    )


def test_report_content_creates_audited_open_report() -> None:
    """8.12.4.4 a patient can report published content with a reason."""
    clinic, _admin_user = _admin()
    patient = _patient(clinic)
    content = _published_content(clinic, _admin_user, "conteudo-reportavel")

    report = content_services.report_content(
        clinic_id=clinic.pk,
        user=patient,
        content_id=content.pk,
        reason="Conteúdo desatualizado.",
        request_id=uuid4(),
    )

    assert report.status == content_models.ContentReport.Status.OPEN
    assert report.reason == "Conteúdo desatualizado."
    assert report.reporter_id == patient.pk
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="content_report", resource_id=str(report.pk), action="create"
        )
        .exists()
    )


def test_report_content_rejects_unpublished_and_foreign() -> None:
    """8.12.4.4 reports only target published, tenant-local content."""
    clinic, admin = _admin()
    patient = _patient(clinic)
    draft = content_models.Content.infrastructure_objects.create(
        clinic=clinic,
        slug="rascunho",
        title="Rascunho",
        kind=content_models.ContentKind.ARTICLE,
        status=content_models.ContentStatus.DRAFT,
        current_version=1,
        created_by=admin,
    )
    with pytest.raises(ValidationError):
        content_services.report_content(
            clinic_id=clinic.pk,
            user=patient,
            content_id=draft.pk,
            reason="Rascunho não deveria ser reportável.",
            request_id=uuid4(),
        )

    other_clinic, other_admin = _admin()
    foreign = _published_content(other_clinic, other_admin, "conteudo-alheio")
    with pytest.raises(PermissionDenied):
        content_services.report_content(
            clinic_id=clinic.pk,
            user=patient,
            content_id=foreign.pk,
            reason="Conteúdo de outra clínica.",
            request_id=uuid4(),
        )


def test_resolve_content_report_is_admin_only_and_audited() -> None:
    """8.12.4.4 an admin resolves a report with a documented decision."""
    clinic, admin = _admin()
    patient = _patient(clinic)
    content = _published_content(clinic, admin, "conteudo-resolvido")
    report = content_services.report_content(
        clinic_id=clinic.pk,
        user=patient,
        content_id=content.pk,
        reason="Revisar.",
        request_id=uuid4(),
    )

    resolved = content_services.resolve_content_report(
        clinic_id=clinic.pk,
        actor=admin,
        report_id=report.pk,
        resolution="resolved",
        note="Conteúdo revisado e mantido.",
        request_id=uuid4(),
    )

    assert resolved.status == content_models.ContentReport.Status.RESOLVED
    assert resolved.resolution_note == "Conteúdo revisado e mantido."
    assert resolved.resolved_by_id == admin.pk
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            resource_type="content_report", resource_id=str(report.pk), action="update"
        )
        .exists()
    )

    with pytest.raises(PermissionDenied):
        content_services.resolve_content_report(
            clinic_id=clinic.pk,
            actor=patient,
            report_id=report.pk,
            resolution="resolved",
            note="Não autorizado.",
            request_id=uuid4(),
        )


def test_archive_content_links_controlled_successor() -> None:
    """8.12.4.4 archiving can point to a published replacement content."""
    clinic, admin = _admin()
    old = _published_content(clinic, admin, "conteudo-antigo")
    successor = _published_content(clinic, admin, "conteudo-novo")

    archived = content_services.archive_content(
        clinic_id=clinic.pk,
        actor=admin,
        content_id=old.pk,
        successor_id=successor.pk,
        request_id=uuid4(),
    )

    assert archived.status == content_models.ContentStatus.ARCHIVED
    assert archived.successor_id == successor.pk


def test_archive_content_rejects_foreign_or_unpublished_successor() -> None:
    """8.12.4.4 the successor must be published and tenant-local."""
    clinic, admin = _admin()
    old = _published_content(clinic, admin, "conteudo-antigo-2")
    draft = content_models.Content.infrastructure_objects.create(
        clinic=clinic,
        slug="sucessor-rascunho",
        title="Sucessor rascunho",
        kind=content_models.ContentKind.ARTICLE,
        status=content_models.ContentStatus.DRAFT,
        current_version=1,
        created_by=admin,
    )
    with pytest.raises(ValidationError):
        content_services.archive_content(
            clinic_id=clinic.pk,
            actor=admin,
            content_id=old.pk,
            successor_id=draft.pk,
            request_id=uuid4(),
        )

    other_clinic, other_admin = _admin()
    foreign = _published_content(other_clinic, other_admin, "sucessor-alheio")
    with pytest.raises(PermissionDenied):
        content_services.archive_content(
            clinic_id=clinic.pk,
            actor=admin,
            content_id=old.pk,
            successor_id=foreign.pk,
            request_id=uuid4(),
        )


def test_review_due_selector_flags_expired_reviews() -> None:
    """8.12.4.4 published content with an expired signed review is surfaced."""
    from datetime import timedelta

    from django.utils import timezone

    clinic, admin = _admin()
    content = _published_content(clinic, admin, "conteudo-vencido")
    version = content_models.ContentVersion.infrastructure_objects.create(
        clinic=clinic,
        content=content,
        version=1,
        body="Corpo.",
        status=content_models.ContentStatus.PUBLISHED,
        review_valid_until=timezone.localdate() - timedelta(days=1),
    )
    content.current_version = version.version
    content.save(update_fields=("current_version", "updated_at"))

    due = content_services.review_due_content(clinic_id=clinic.pk)

    assert any(item.pk == content.pk for item in due)


def test_report_http_surface_lists_and_resolves(client: Client) -> None:
    """8.12.4.4 admins can list and resolve reports over HTTP."""
    clinic, admin = _admin()
    patient = _patient(clinic)
    content = _published_content(clinic, admin, "conteudo-http")
    report = content_services.report_content(
        clinic_id=clinic.pk,
        user=patient,
        content_id=content.pk,
        reason="Revisar via HTTP.",
        request_id=uuid4(),
    )
    client.force_login(admin)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    listing = client.get(reverse("content_reports"))
    assert listing.status_code == 200
    assert "Revisar via HTTP." in listing.content.decode()

    resolved = client.post(
        reverse("content_report_resolve", args=[report.pk]),
        {"resolution": "resolved", "note": "Resolvido via HTTP."},
    )
    assert resolved.status_code == 302
    report.refresh_from_db()
    assert report.status == content_models.ContentReport.Status.RESOLVED
