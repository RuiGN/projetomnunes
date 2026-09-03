"""Security and lifecycle regressions for PRD 8.12.1."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from content import services as content_services
from content.models import Content, ContentKind
from content.services import (
    approve_content_version,
    attach_media,
    create_content_version,
    publish_content_version,
    start_content,
    submit_for_review,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _administrator() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    actor = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=actor,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return clinic, actor


def _draft(
    clinic: Clinic,
    actor: User,
    *,
    valid_until: date | None = None,
) -> Content:
    return start_content(
        clinic_id=clinic.pk,
        actor=actor,
        slug="conteudo-seguro",
        title="Conteúdo seguro",
        kind=ContentKind.ARTICLE,
        body="Conteúdo sintético.",
        valid_until=valid_until,
        request_id=uuid4(),
    )


def test_start_content_persists_the_declared_validity_date() -> None:
    clinic, actor = _administrator()
    expected = date.today() + timedelta(days=30)

    content = _draft(clinic, actor, valid_until=expected)

    content.refresh_from_db()
    assert content.valid_until == expected


def test_content_media_rejects_spoofed_declared_mime_type() -> None:
    clinic, actor = _administrator()
    content = _draft(clinic, actor)
    executable = SimpleUploadedFile(
        "imagem.png",
        b"#!/bin/sh\nexit 0",
        content_type="image/png",
    )

    with pytest.raises(ValidationError, match="conteúdo|arquivo"):
        attach_media(
            clinic_id=clinic.pk,
            actor=actor,
            content_id=content.pk,
            uploaded=executable,
            content_type="image/png",
            original_name="imagem.png",
            request_id=uuid4(),
        )


def test_scheduled_content_cannot_publish_before_its_server_time() -> None:
    clinic, actor = _administrator()
    reviewer = _administrator()[1]
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=reviewer,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    _give_verified_credential(clinic, actor)
    _give_verified_credential(clinic, reviewer)
    content = _draft(clinic, actor)
    create_content_version(
        clinic_id=clinic.pk,
        actor=actor,
        content_id=content.pk,
        body="Versão agendada.",
        scheduled_for=timezone.now() + timedelta(hours=1),
        request_id=uuid4(),
    )
    submit_for_review(
        clinic_id=clinic.pk,
        actor=actor,
        content_id=content.pk,
        request_id=uuid4(),
    )
    approve_content_version(
        clinic_id=clinic.pk,
        actor=reviewer,
        content_id=content.pk,
        opinion="Parecer favorável ao agendamento.",
        review_valid_days=30,
        request_id=uuid4(),
    )

    publisher = _administrator()[1]
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=publisher,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    _give_verified_credential(clinic, publisher)
    with pytest.raises(ValidationError, match="agend"):
        publish_content_version(
            clinic_id=clinic.pk,
            actor=publisher,
            content_id=content.pk,
            request_id=uuid4(),
        )


def _give_verified_credential(clinic: Clinic, professional: User) -> None:
    """Grant one verified council credential for editorial governance tests."""
    from people.models import ProfessionalCredential, ProfessionalProfile

    profile = ProfessionalProfile.infrastructure_objects.create(
        clinic=clinic,
        user=professional,
        full_name=f"Prof. {professional.pk}",
        professional_email=professional.email,
        category="psychologist",
    )
    ProfessionalCredential.objects.create(
        profile=profile,
        status=ProfessionalCredential.Status.VERIFIED,
        council_name="CRP",
        council_number=uuid4().hex[:6],
        council_jurisdiction="PE",
    )


@pytest.mark.parametrize(
    "payload",
    [
        '<a href="java&#x73;cript:alert(1)">link</a>',
        '<object data="data:text/html;base64,PHNjcmlwdD4="></object>',
        '<svg><a xlink:href="javascript&colon;alert(1)">link</a></svg>',
    ],
)
def test_content_sanitization_rejects_encoded_active_markup(payload: str) -> None:
    sanitized = content_services.sanitize_body(payload).lower()

    assert "javascript" not in sanitized
    assert "data:text/html" not in sanitized
    assert "<object" not in sanitized
    assert "<svg" not in sanitized


def test_content_media_runs_fail_closed_malware_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clinic, actor = _administrator()
    content = _draft(clinic, actor)
    upload = SimpleUploadedFile(
        "imagem.png",
        b"\x89PNG\r\n\x1a\nsynthetic",
        content_type="image/png",
    )
    scanned: list[object] = []

    def record_scan(candidate: object) -> None:
        scanned.append(candidate)

    monkeypatch.setattr(content_services, "require_clean_malware_scan", record_scan)

    attach_media(
        clinic_id=clinic.pk,
        actor=actor,
        content_id=content.pk,
        uploaded=upload,
        content_type="image/png",
        original_name="imagem.png",
        request_id=uuid4(),
    )

    assert scanned == [upload]


def test_production_exports_the_private_content_media_root() -> None:
    production_settings = (
        PROJECT_ROOT / "config" / "settings" / "production.py"
    ).read_text(encoding="utf-8")

    assert "PRIVATE_MEDIA_ROOT" in production_settings
