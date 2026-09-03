"""Acceptance tests for PRD 8.12.5 white label, custom domains, and templates."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from audit.models import AuditAction, AuditEvent
from clinics.models import Clinic, ClinicMembership, CommunicationTemplate, CustomDomain
from clinics.whitelabel_services import (
    activate_custom_domain,
    approve_and_activate_communication_template,
    calculate_contrast_ratio,
    create_communication_template,
    register_custom_domain,
    render_communication_template,
    resolve_clinic_by_custom_domain,
    revoke_custom_domain,
    rollback_brand_theme,
    send_test_communication,
    update_brand_theme,
    validate_brand_contrast,
    verify_and_provision_custom_domain,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _create_admin_and_clinic() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def _create_therapist(clinic: Clinic) -> User:
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    return therapist


# ---------------------------------------------------------------------------
# 8.12.5.1 — Design tokens, contrast calculation and rollback
# ---------------------------------------------------------------------------


def test_calculate_contrast_ratio_standard_values() -> None:
    """Black on white must achieve 21:1, white on white must be 1:1."""
    assert calculate_contrast_ratio("#000000", "#FFFFFF") == 21.0
    assert calculate_contrast_ratio("#FFFFFF", "#FFFFFF") == 1.0
    # Accessible dark text on light background
    ratio = calculate_contrast_ratio("#151515", "#F9FBFD")
    assert ratio >= 4.5


def test_validate_brand_contrast_detects_low_contrast() -> None:
    """Low contrast combinations must produce descriptive validation errors."""
    bad_tokens = {
        "text_color": "#CCCCCC",
        "background_color": "#FFFFFF",
        "surface_color": "#FFFFFF",
        "primary_color": "#DDDDDD",
    }
    errors = validate_brand_contrast(bad_tokens)
    assert len(errors) >= 2
    assert any("texto" in err for err in errors)
    assert any("primária" in err for err in errors)


def test_update_brand_theme_creates_version_and_updates_config() -> None:
    """Valid brand tokens update config, versioning, and audit."""
    clinic, admin = _create_admin_and_clinic()
    tokens = {
        "text_color": "#151515",
        "background_color": "#F9FBFD",
        "surface_color": "#FFFFFF",
        "primary_color": "#6A69F5",
        "secondary_color": "#50CD89",
        "display_name": "Clínica Vida Nova",
    }

    v1 = update_brand_theme(
        clinic_id=clinic.pk,
        actor=admin,
        tokens=tokens,
        notes="Identidade visual inicial",
        request_id=uuid4(),
    )
    assert v1.version == 1
    assert v1.tokens == tokens
    assert v1.clinic_id == clinic.pk

    # Audit event recorded
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(action=AuditAction.UPDATE, resource_id=str(v1.pk))
        .exists()
    )

    # Next update increments version
    tokens_v2 = dict(tokens, primary_color="#1D4ED8")
    v2 = update_brand_theme(
        clinic_id=clinic.pk,
        actor=admin,
        tokens=tokens_v2,
        notes="Ajuste cor primária",
        request_id=uuid4(),
    )
    assert v2.version == 2


def test_rollback_brand_theme_restores_previous_tokens() -> None:
    """Rollback creates a new version restoring prior tokens with audit."""
    clinic, admin = _create_admin_and_clinic()
    tokens_v1 = {
        "text_color": "#151515",
        "background_color": "#F9FBFD",
        "surface_color": "#FFFFFF",
        "primary_color": "#6A69F5",
    }
    tokens_v2 = dict(tokens_v1, primary_color="#1D4ED8")

    update_brand_theme(
        clinic_id=clinic.pk, actor=admin, tokens=tokens_v1, request_id=uuid4()
    )
    update_brand_theme(
        clinic_id=clinic.pk, actor=admin, tokens=tokens_v2, request_id=uuid4()
    )

    # Rollback to v1
    v3 = rollback_brand_theme(
        clinic_id=clinic.pk, actor=admin, target_version=1, request_id=uuid4()
    )
    assert v3.version == 3
    assert v3.tokens["primary_color"] == "#6A69F5"

    # Fails for non-existent version
    with pytest.raises(ValidationError):
        rollback_brand_theme(
            clinic_id=clinic.pk, actor=admin, target_version=99, request_id=uuid4()
        )


# ---------------------------------------------------------------------------
# 8.12.5.2 — Custom domain, TLS provisioning, and routing cache
# ---------------------------------------------------------------------------


def test_custom_domain_lifecycle_and_tls_provisioning() -> None:
    """Registering, verifying, provisioning TLS, and activating custom domain."""
    clinic, admin = _create_admin_and_clinic()
    domain_name = "terapia.meuconsultorio.com.br"

    # Register
    custom_domain = register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain=domain_name,
        request_id=uuid4(),
    )
    assert custom_domain.status == CustomDomain.Status.PENDING
    assert "projetomnunes-verify=" in custom_domain.verification_token

    # Verify and provision TLS (explicit simulated adapter injection: tests only)
    from datetime import timedelta

    from django.utils import timezone as tz

    class RealAdapterStub:
        """A non-simulated adapter stands in for a production ACME/DNS one."""

        simulated = False

        def verify_dns_challenge(self, domain: str, expected_token: str) -> bool:
            return True

        def provision_certificate(self, domain: str) -> dict[str, Any]:
            now = tz.now()
            return {
                "status": "active",
                "provisioned_at": now,
                "expires_at": now + timedelta(days=90),
                "issuer": "Real CA",
                "simulated": False,
            }

    verified = verify_and_provision_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain_id=custom_domain.pk,
        tls_adapter=RealAdapterStub(),
        request_id=uuid4(),
    )
    assert verified.status == CustomDomain.Status.VERIFIED
    assert verified.tls_status == CustomDomain.TlsStatus.ACTIVE
    assert verified.tls_expires_at is not None

    # Activate
    activated = activate_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain_id=custom_domain.pk,
        request_id=uuid4(),
    )
    assert activated.status == CustomDomain.Status.ACTIVE
    assert activated.is_primary is True

    # Resolve domain routes to clinic
    resolved = resolve_clinic_by_custom_domain(domain_name)
    assert resolved is not None
    assert resolved.pk == clinic.pk

    # Revoke custom domain clears routing
    revoke_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain_id=custom_domain.pk,
        request_id=uuid4(),
    )
    assert resolve_clinic_by_custom_domain(domain_name) is None


def test_custom_domain_rejects_invalid_names_and_duplicates() -> None:
    """Rejects invalid hostnames, localhost, and duplicate domain registrations."""
    clinic, admin = _create_admin_and_clinic()

    with pytest.raises(ValidationError):
        register_custom_domain(
            clinic_id=clinic.pk, actor=admin, domain="localhost", request_id=uuid4()
        )

    with pytest.raises(ValidationError):
        register_custom_domain(
            clinic_id=clinic.pk,
            actor=admin,
            domain="http://bad domain.com",
            request_id=uuid4(),
        )

    register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain="clinica.exemplo.com",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        register_custom_domain(
            clinic_id=clinic.pk,
            actor=admin,
            domain="clinica.exemplo.com",
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.12.5.3 — Versioned communication templates
# ---------------------------------------------------------------------------


def test_create_and_render_communication_template() -> None:
    """Create template, validate variables, sanitize XSS, approve and render."""
    clinic, admin = _create_admin_and_clinic()

    template = create_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel=CommunicationTemplate.Channel.EMAIL,
        purpose="lembrete_consulta",
        subject="Lembrete de consulta com {{ professional_name }}",
        body="Olá {{ patient_name }}, sua sessão é em {{ date }}.",
        allowed_variables=["professional_name", "patient_name", "date"],
        request_id=uuid4(),
    )
    assert template.version == 1
    assert template.status == CommunicationTemplate.Status.DRAFT

    # Approve and activate
    approved = approve_and_activate_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        template_id=template.pk,
        request_id=uuid4(),
    )
    assert approved.status == CommunicationTemplate.Status.ACTIVE

    # Render
    rendered = render_communication_template(
        approved,
        {
            "professional_name": "Dra. Ana",
            "patient_name": "João",
            "date": "10/10/2026",
        },
    )
    assert rendered["subject"] == "Lembrete de consulta com Dra. Ana"
    assert rendered["body"] == "Olá João, sua sessão é em 10/10/2026."


def test_template_rejects_dangerous_content_and_unauthorized_variables() -> None:
    """Sanitizer blocks script tags and unallowed template variables."""
    clinic, admin = _create_admin_and_clinic()

    with pytest.raises(ValidationError):
        create_communication_template(
            clinic_id=clinic.pk,
            actor=admin,
            channel=CommunicationTemplate.Channel.EMAIL,
            purpose="teste",
            subject="Olá",
            body="Texto com <script>alert(1)</script>",
            allowed_variables=[],
            request_id=uuid4(),
        )

    with pytest.raises(ValidationError):
        create_communication_template(
            clinic_id=clinic.pk,
            actor=admin,
            channel=CommunicationTemplate.Channel.EMAIL,
            purpose="teste",
            subject="Olá",
            body="Olá {{ unauthorized_variable }}",
            allowed_variables=["authorized_var"],
            request_id=uuid4(),
        )


def test_send_test_communication_dispatches_and_audits() -> None:
    """Test send dispatches communication and records audit trail."""
    clinic, admin = _create_admin_and_clinic()
    template = create_communication_template(
        clinic_id=clinic.pk,
        actor=admin,
        channel=CommunicationTemplate.Channel.EMAIL,
        purpose="boas_vindas",
        subject="Bem-vindo à {{ clinic_name }}",
        body="Olá {{ name }}, seja bem-vindo!",
        allowed_variables=["clinic_name", "name"],
        request_id=uuid4(),
    )
    result = send_test_communication(
        clinic_id=clinic.pk,
        actor=admin,
        template_id=template.pk,
        recipient_email="teste@exemplo.com",
        sample_context={"clinic_name": "Minha Clínica", "name": "Admin"},
        request_id=uuid4(),
    )
    assert result["status"] == "sent"
    audit_event = AuditEvent.infrastructure_objects.get(
        clinic_id=clinic.pk,
        action=AuditAction.VIEW,
        resource_type="communication_template",
        resource_id=str(template.pk),
    )
    assert audit_event.justification_digest
    assert "test_sent:teste@exemplo.com" not in audit_event.justification_digest


# ---------------------------------------------------------------------------
# 8.12.5.4 — Tenant isolation and administrative permissions
# ---------------------------------------------------------------------------


def test_whitelabel_tenant_isolation_and_permissions() -> None:
    """Cross-tenant operations are denied and non-admins cannot manage whitelabel."""
    clinic_a, admin_a = _create_admin_and_clinic()
    clinic_b, admin_b = _create_admin_and_clinic()
    therapist_a = _create_therapist(clinic_a)

    # Therapist cannot update theme
    with pytest.raises(PermissionDenied):
        update_brand_theme(
            clinic_id=clinic_a.pk,
            actor=therapist_a,
            tokens={"text_color": "#151515"},
            request_id=uuid4(),
        )

    # Admin A creates a custom domain
    domain_a = register_custom_domain(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        domain="clinica-a.com.br",
        request_id=uuid4(),
    )

    # Admin B cannot verify or modify Admin A's domain
    with pytest.raises(PermissionDenied):
        verify_and_provision_custom_domain(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            domain_id=domain_a.pk,
            request_id=uuid4(),
        )

    # Admin B cannot rollback Admin A's theme
    v_a = update_brand_theme(
        clinic_id=clinic_a.pk,
        actor=admin_a,
        tokens={
            "text_color": "#151515",
            "background_color": "#F9FBFD",
            "surface_color": "#FFFFFF",
            "primary_color": "#6A69F5",
        },
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        rollback_brand_theme(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            target_version=v_a.version,
            request_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 8.12.5.2 — fail-closed TLS adapter governance (round-2 review Critical C1)
# ---------------------------------------------------------------------------


def test_domain_verification_requires_configured_adapter() -> None:
    """Without an injected or configured adapter, verification is refused."""
    from clinics.whitelabel_services import FailClosedTlsAdapterError

    clinic, admin = _create_admin_and_clinic()
    custom_domain = register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain="falha-fechada.com.br",
        request_id=uuid4(),
    )
    with pytest.raises(FailClosedTlsAdapterError):
        verify_and_provision_custom_domain(
            clinic_id=clinic.pk,
            actor=admin,
            domain_id=custom_domain.pk,
            request_id=uuid4(),
        )
    custom_domain.refresh_from_db()
    assert custom_domain.status == CustomDomain.Status.PENDING


def test_real_adapter_produces_verified_state_and_simulated_does_not() -> None:
    """A non-simulated adapter may persist VERIFIED/ACTIVE; the stub may not."""
    from clinics.whitelabel_services import DefaultTlsAdapter

    class RealAdapterStub:
        simulated = False

        def verify_dns_challenge(self, domain: str, expected_token: str) -> bool:
            return True

        def provision_certificate(self, domain: str) -> dict[str, Any]:
            from django.utils import timezone

            now = timezone.now()
            return {
                "status": "active",
                "provisioned_at": now,
                "expires_at": now + timedelta(days=90),
                "issuer": "Real CA",
                "simulated": False,
            }

    clinic, admin = _create_admin_and_clinic()
    real_domain = register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain="real-adapter.com.br",
        request_id=uuid4(),
    )
    verified = verify_and_provision_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain_id=real_domain.pk,
        tls_adapter=RealAdapterStub(),
        request_id=uuid4(),
    )
    assert verified.status == CustomDomain.Status.VERIFIED
    assert verified.tls_status == CustomDomain.TlsStatus.ACTIVE
    assert verified.tls_expires_at is not None

    stub_domain = register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain="stub-adapter.com.br",
        request_id=uuid4(),
    )
    stub_result = verify_and_provision_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain_id=stub_domain.pk,
        tls_adapter=DefaultTlsAdapter(),
        request_id=uuid4(),
    )
    assert stub_result.status == CustomDomain.Status.PENDING
    assert stub_result.tls_status == CustomDomain.TlsStatus.PENDING


def test_failed_dns_challenge_marks_domain_failed() -> None:
    """A negative ownership check persists FAILED and refuses verification."""
    from clinics.whitelabel_services import DefaultTlsAdapter

    class RejectingAdapter(DefaultTlsAdapter):
        def verify_dns_challenge(self, domain: str, expected_token: str) -> bool:
            return False

    clinic, admin = _create_admin_and_clinic()
    custom_domain = register_custom_domain(
        clinic_id=clinic.pk,
        actor=admin,
        domain="dns-recusado.com.br",
        request_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        verify_and_provision_custom_domain(
            clinic_id=clinic.pk,
            actor=admin,
            domain_id=custom_domain.pk,
            tls_adapter=RejectingAdapter(),
            request_id=uuid4(),
        )
    custom_domain.refresh_from_db()
    assert custom_domain.status == CustomDomain.Status.FAILED
