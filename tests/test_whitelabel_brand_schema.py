"""Acceptance tests for PRD 8.12.5.1/8.12.5.2 residual gaps
(brand schema + domain fallback)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

import clinics.whitelabel_services as wl
from accounts.models import User
from clinics.models import Clinic, ClinicConfiguration, ClinicMembership, CustomDomain
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin() -> tuple[Clinic, User]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    return clinic, admin


def _config(clinic: Clinic) -> ClinicConfiguration:
    return ClinicConfiguration.infrastructure_objects.create(
        clinic=clinic,
        legal_name="Clínica Exemplo Ltda",
        display_name="Clínica Exemplo",
        administrative_email="admin@exemplo.test",
        address_line_1="Rua A",
        city="Recife",
        region="PE",
        postal_code="50000-000",
        country_code="BR",
    )


def test_update_brand_identity_persists_full_schema() -> None:
    """8.12.5.1 icons, typography, legal texts, sender and links are authorable."""
    clinic, admin = _admin()
    _config(clinic)

    wl.update_brand_identity(
        clinic_id=clinic.pk,
        actor=admin,
        icon="https://cdn.exemplo.test/icon.svg",
        typography="Cerebri Sans",
        legal_text="Termos de uso da clínica.",
        sender_name="Clínica Exemplo",
        sender_email="contato@exemplo.test",
        institutional_links=["https://exemplo.test/sobre"],
        request_id=uuid4(),
    )

    refreshed = ClinicConfiguration.infrastructure_objects.get(clinic=clinic)
    assert refreshed.icon == "https://cdn.exemplo.test/icon.svg"
    assert refreshed.typography == "Cerebri Sans"
    assert refreshed.legal_text == "Termos de uso da clínica."
    assert refreshed.sender_name == "Clínica Exemplo"
    assert refreshed.sender_email == "contato@exemplo.test"
    assert refreshed.institutional_links == ["https://exemplo.test/sobre"]


def test_update_brand_identity_is_admin_only() -> None:
    """8.12.5.1 brand identity changes require clinic administration."""
    clinic, _admin_user = _admin()
    _config(clinic)
    outsider = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=outsider, role=ClinicMembership.Role.PATIENT
    )

    with pytest.raises(PermissionDenied):
        wl.update_brand_identity(
            clinic_id=clinic.pk,
            actor=outsider,
            icon="https://cdn.exemplo.test/icon.svg",
            typography="Cerebri Sans",
            legal_text="Termos.",
            sender_name="Clínica",
            sender_email="contato@exemplo.test",
            institutional_links=[],
            request_id=uuid4(),
        )


def test_resolve_clinic_by_custom_domain_falls_back_to_none() -> None:
    """8.12.5.2 an unknown host resolves to None (default-domain fallback)."""
    clinic, admin = _admin()
    CustomDomain.infrastructure_objects.create(
        clinic=clinic,
        domain="clinica.exemplo.com.br",
        verification_token="token",
        status=CustomDomain.Status.ACTIVE,
        tls_status=CustomDomain.TlsStatus.ACTIVE,
        created_by=admin,
    )

    assert wl.resolve_clinic_by_custom_domain("desconhecido.exemplo.com") is None
    assert wl.resolve_clinic_by_custom_domain("clinica.exemplo.com.br") is not None


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
