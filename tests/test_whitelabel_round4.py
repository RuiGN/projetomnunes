"""Acceptance tests for PRD 8.12.5 residual gaps (round-3 Important findings)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

import clinics.whitelabel_services as wl
from accounts.models import User
from clinics.models import Clinic, ClinicMembership, CommunicationTemplate, CustomDomain
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def test_sanitizer_allowlist_blocks_active_content() -> None:
    """8.12.5.3 the sanitizer rejects active content beyond the old denylist."""
    for payload in (
        "<base href='https://evil.test'>",
        "<form action='https://evil.test'>",
        "<link rel='stylesheet' href='https://evil.test'>",
        "<meta http-equiv='refresh' content='0;url=https://evil.test'>",
        "<a href='data:text/html,<script>alert(1)</script>'>x</a>",
        "<a href='vbscript:msgbox(1)'>x</a>",
        "<svg onload='alert(1)'>",
    ):
        with pytest.raises(ValidationError):
            wl.sanitize_template_content(payload)


def test_sanitizer_allowlist_permits_plain_markup() -> None:
    """8.12.5.3 benign markup and variables pass the allowlist sanitizer."""
    body = "<p>Olá {{ name }}, <strong>bem-vindo</strong>.</p>"
    assert wl.sanitize_template_content(body) == body


def test_rollback_communication_template_restores_previous_active() -> None:
    """8.12.5.4 a template can be rolled back to a prior active version."""
    clinic, admin = _admin()
    v1 = wl.create_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel="email",
        purpose="welcome",
        subject="Bem-vindo v1",
        body="Corpo v1.",
        allowed_variables=["name"],
        request_id=uuid4(),
    )
    wl.approve_and_activate_communication_template(
        clinic_id=clinic.pk, actor=admin, template_id=v1.pk, request_id=uuid4()
    )
    v2 = wl.create_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel="email",
        purpose="welcome",
        subject="Bem-vindo v2",
        body="Corpo v2.",
        allowed_variables=["name"],
        request_id=uuid4(),
    )
    wl.approve_and_activate_communication_template(
        clinic_id=clinic.pk, actor=admin, template_id=v2.pk, request_id=uuid4()
    )

    rolled_back = wl.rollback_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel="email",
        purpose="welcome",
        target_version=1,
        request_id=uuid4(),
    )

    assert rolled_back.version == 3
    assert rolled_back.subject == "Bem-vindo v1"
    assert rolled_back.status == CommunicationTemplate.Status.ACTIVE


def test_send_test_communication_is_honest_for_non_email() -> None:
    """8.12.5.3 non-email test-send returns a preview, not a false 'sent'."""
    clinic, admin = _admin()
    template = wl.create_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel="notification",
        purpose="reminder",
        subject="Lembrete",
        body="Olá {{ name }}.",
        allowed_variables=["name"],
        request_id=uuid4(),
    )

    result = wl.send_test_communication(
        clinic_id=clinic.pk,
        actor=admin,
        template_id=template.pk,
        recipient_email="admin@example.test",
        sample_context={"name": "Pessoa"},
        request_id=uuid4(),
    )

    assert result["status"] == "preview"
    assert result["rendered"]["body"] == "Olá Pessoa."


def test_tls_renewal_monitor_marks_due_domains() -> None:
    """8.12.5.2 a management command flags domains nearing TLS expiry."""
    from datetime import timedelta

    from django.utils import timezone

    clinic, admin = _admin()
    domain = CustomDomain.infrastructure_objects.create(
        clinic=clinic,
        domain="clinica.exemplo.com.br",
        verification_token="token",
        status=CustomDomain.Status.ACTIVE,
        tls_status=CustomDomain.TlsStatus.ACTIVE,
        tls_expires_at=timezone.now() + timedelta(days=10),
        created_by=admin,
    )

    due = wl.renewal_due_domains(days_before=30)

    assert any(item.pk == domain.pk for item in due)


def test_custom_domain_resolution_returns_active_clinic() -> None:
    """8.12.5.2 an active custom domain resolves to its clinic."""
    clinic, admin = _admin()
    CustomDomain.infrastructure_objects.create(
        clinic=clinic,
        domain="resolucao.exemplo.com.br",
        verification_token="token",
        status=CustomDomain.Status.ACTIVE,
        tls_status=CustomDomain.TlsStatus.ACTIVE,
        created_by=admin,
    )

    resolved = wl.resolve_clinic_by_custom_domain("resolucao.exemplo.com.br")

    assert resolved is not None
    assert resolved.pk == clinic.pk


def test_whitelabel_http_surface_lists_domains(client: Client) -> None:
    """8.12.5.4 admins can view their custom domains over HTTP."""
    clinic, admin = _admin()
    CustomDomain.infrastructure_objects.create(
        clinic=clinic,
        domain="clinica.exemplo.com.br",
        verification_token="token",
        status=CustomDomain.Status.PENDING,
        created_by=admin,
    )
    client.force_login(admin)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("whitelabel_domains"))

    assert response.status_code == 200
    assert "clinica.exemplo.com.br" in response.content.decode()
