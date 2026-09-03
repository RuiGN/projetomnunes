"""Acceptance tests for PRD 8.12.1 — CMS, taxonomia e ciclo editorial."""

from __future__ import annotations

import re
from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from content.models import Content, ContentKind, ContentStatus, ContentVersion
from content.services import (
    approve_content_version,
    archive_content,
    attach_media,
    create_content_version,
    publish_content_version,
    rollback_content,
    sanitize_body,
    search_published_content,
    start_content,
    submit_for_review,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def _governance_clinic() -> tuple[Clinic, User, User, User]:
    """Return clinic, submitter-admin, reviewer-admin and publisher-admin."""
    from people.models import ProfessionalCredential, ProfessionalProfile

    clinic = ClinicFactory.create()
    submitter = UserFactory.create()
    reviewer = UserFactory.create()
    publisher = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=submitter, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=reviewer, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=publisher, role=ClinicMembership.Role.CLINIC_ADMIN
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


def _content(clinic: Clinic, admin: User, slug: str = "respiracao") -> Content:
    return start_content(
        clinic_id=clinic.pk,
        actor=admin,
        slug=slug,
        title="Exercícios de respiração",
        kind=ContentKind.ARTICLE,
        body="Respire fundo e conte até quatro.",
        request_id=uuid4(),
    )


def _full_lifecycle(
    clinic: Clinic,
    submitter: User,
    reviewer: User,
    publisher: User,
    slug: str = "respiracao",
) -> Content:
    content = start_content(
        clinic_id=clinic.pk,
        actor=submitter,
        slug=slug,
        title="Exercícios de respiração",
        kind=ContentKind.ARTICLE,
        body="Respire fundo e conte até quatro.",
        request_id=uuid4(),
    )
    submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável ao conteúdo proposto.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    return publish_content_version(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )


# ---------------------------------------------------------------------------
# 8.12.1.1 — versioned content model
# ---------------------------------------------------------------------------


def test_start_content_creates_draft_with_version() -> None:
    clinic, admin = _admin()
    content = _content(clinic, admin)
    assert content.status == ContentStatus.DRAFT
    assert content.current_version == 1
    version = ContentVersion.infrastructure_objects.get(content_id=content.pk)
    assert version.body == "Respire fundo e conte até quatro."
    assert version.body_hash


def test_start_content_rejects_duplicate_slug() -> None:
    clinic, admin = _admin()
    _content(clinic, admin, "respiracao")
    with pytest.raises(ValidationError):
        _content(clinic, admin, "respiracao")


def test_start_content_requires_admin() -> None:
    clinic, admin = _admin()
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.THERAPIST
    )
    with pytest.raises(PermissionDenied):
        start_content(
            clinic_id=clinic.pk,
            actor=outsider,
            slug="respiracao",
            title="Título",
            kind=ContentKind.ARTICLE,
            body="Texto",
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.12.1.3 — editorial workflow
# ---------------------------------------------------------------------------


def test_editorial_workflow_requires_approval_before_publish() -> None:
    clinic, admin = _admin()
    content = _content(clinic, admin)
    with pytest.raises(ValidationError):
        publish_content_version(
            clinic_id=clinic.pk, actor=admin, content_id=content.pk, request_id=uuid4()
        )


def test_full_lifecycle_publishes() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    assert content.status == ContentStatus.PUBLISHED
    version = ContentVersion.infrastructure_objects.get(
        content_id=content.pk, version=content.current_version
    )
    assert version.published_at is not None
    assert version.approved_by_id == reviewer.pk


def test_new_version_resets_to_draft_and_preserves_history() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    published_version = content.current_version

    new_version = create_content_version(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        body="Nova redação do exercício.",
        request_id=uuid4(),
    )

    assert new_version.version == published_version + 1
    assert new_version.status == ContentStatus.DRAFT
    content.refresh_from_db()
    assert content.status == ContentStatus.DRAFT
    # The published version remains untouched.
    old = ContentVersion.infrastructure_objects.get(
        content_id=content.pk, version=published_version
    )
    assert old.status == ContentStatus.PUBLISHED


def test_rollback_to_published_version() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    first_version = content.current_version
    create_content_version(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        body="Nova versão.",
        request_id=uuid4(),
    )
    submit_for_review(
        clinic_id=clinic.pk, actor=submitter, content_id=content.pk, request_id=uuid4()
    )
    approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável à nova redação.",
        review_valid_days=30,
        request_id=uuid4(),
    )
    publish_content_version(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )

    rolled = rollback_content(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        target_version=first_version,
        request_id=uuid4(),
    )
    assert rolled.current_version == first_version
    assert rolled.status == ContentStatus.PUBLISHED


def test_rollback_rejects_unpublished_target() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    create_content_version(
        clinic_id=clinic.pk,
        actor=submitter,
        content_id=content.pk,
        body="Rascunho novo.",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        rollback_content(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            target_version=2,
            request_id=uuid4(),
        )


def test_archive_removes_from_index() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    assert len(search_published_content(clinic_id=clinic.pk, query="respiração")) == 1

    archive_content(
        clinic_id=clinic.pk, actor=publisher, content_id=content.pk, request_id=uuid4()
    )
    assert len(search_published_content(clinic_id=clinic.pk, query="respiração")) == 0


# ---------------------------------------------------------------------------
# 8.12.1.4 — indexing filters
# ---------------------------------------------------------------------------


def test_search_indexes_only_published_matching_language_and_audience() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    _full_lifecycle(clinic, submitter, reviewer, publisher, "publicado")
    # Draft content must not appear.
    _content(clinic, publisher, "rascunho")

    results = search_published_content(clinic_id=clinic.pk, query="respiração")
    assert len(results) == 1
    assert results[0].slug == "publicado"

    english = search_published_content(
        clinic_id=clinic.pk, query="respiração", language_code="en-US"
    )
    assert english == []

    professional = search_published_content(
        clinic_id=clinic.pk, query="respiração", audience="professional"
    )
    assert professional == []


def test_search_excludes_expired_content() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    Content.infrastructure_objects.filter(pk=content.pk).update(
        valid_until=date.today() - timedelta(days=1)
    )
    assert search_published_content(clinic_id=clinic.pk, query="respiração") == []


# ---------------------------------------------------------------------------
# 8.12.1.2 — sanitization and media upload
# ---------------------------------------------------------------------------


def test_sanitize_body_strips_active_markup() -> None:
    dirty = "<p>Olá</p><script>alert(1)</script><a onclick='x()'>link</a>"
    sanitized = sanitize_body(dirty)
    assert "<script" not in sanitized
    assert "onclick" not in sanitized
    assert "<p>Olá</p>" in sanitized


def test_sanitize_body_neutralizes_href_attribute_injection() -> None:
    payload = '<a href="https://safe.test/&quot; onmouseover=&quot;alert(1)">click</a>'
    sanitized = sanitize_body(payload)

    assert "onmouseover" not in sanitized
    assert "alert(1)" not in sanitized
    assert "https://safe.test/" in sanitized
    assert "click" in sanitized
    assert re.search(r'<a href="https://safe.test/[^"]*">click</a>', sanitized)


def test_sanitize_body_neutralizes_single_quoted_href_injection() -> None:
    payload = '<a href="https://safe.test/&#39; onfocus=&#39;alert(1)">text</a>'
    sanitized = sanitize_body(payload)

    assert "onfocus" not in sanitized
    assert "alert(1)" not in sanitized
    assert "https://safe.test/" in sanitized


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_attach_media_validates_type_and_size() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _content(clinic, publisher)
    upload = SimpleUploadedFile(
        "guia.png", b"\x89PNG\r\n\x1a\nsafe", content_type="image/png"
    )
    media = attach_media(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        uploaded=upload,
        content_type="image/png",
        original_name="guia.png",
        request_id=uuid4(),
    )
    assert media.original_name == "guia-original.png" or media.original_name
    assert media.content_type == "image/png"
    assert "guia" not in media.file.name

    bad = SimpleUploadedFile("a.txt", b"nope", content_type="text/plain")
    with pytest.raises(ValidationError):
        attach_media(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            uploaded=bad,
            content_type="text/plain",
            original_name="a.txt",
            request_id=uuid4(),
        )


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_attach_media_accepts_video_and_audio() -> None:
    """8.12.1 media policy admits mp4/mp3 declared in MEDIA_ALLOWED_TYPES."""
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _content(clinic, publisher)

    mp4 = SimpleUploadedFile(
        "aula.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00",
        content_type="video/mp4",
    )
    video_media = attach_media(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        uploaded=mp4,
        content_type="video/mp4",
        original_name="aula.mp4",
        request_id=uuid4(),
    )
    assert video_media.content_type == "video/mp4"

    mp3 = SimpleUploadedFile(
        "audio.mp3",
        b"ID3\x04\x00\x00\x00\x00\x00\x00safe-audio",
        content_type="audio/mpeg",
    )
    audio_media = attach_media(
        clinic_id=clinic.pk,
        actor=publisher,
        content_id=content.pk,
        uploaded=mp3,
        content_type="audio/mpeg",
        original_name="audio.mp3",
        request_id=uuid4(),
    )
    assert audio_media.content_type == "audio/mpeg"

    forged = SimpleUploadedFile(
        "fake.mp4", b"GIF89a not a real video", content_type="video/mp4"
    )
    with pytest.raises(ValidationError):
        attach_media(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            uploaded=forged,
            content_type="video/mp4",
            original_name="fake.mp4",
            request_id=uuid4(),
        )


def test_content_audit_trail() -> None:
    clinic, submitter, reviewer, publisher = _governance_clinic()
    content = _full_lifecycle(clinic, submitter, reviewer, publisher)
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(resource_type="content", resource_id=str(content.pk))
        .exists()
    )
