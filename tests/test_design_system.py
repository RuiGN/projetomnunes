"""Contracts for the application-owned Duralux asset layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.test import Client
from django.urls import reverse

from accounts.models import User
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db

STATIC_ROOT = Path(settings.BASE_DIR) / "static"
PRODUCT_CSS_PATH = STATIC_ROOT / "duralux" / "css" / "product-integration.css"


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _staff_with_clinic() -> tuple[User, Clinic]:
    user = UserFactory.create(is_staff=True)
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(
        user=user,
        clinic=clinic,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    return user, clinic


def test_duralux_semantic_tokens_and_focus_meet_accessibility_contract() -> None:
    css = PRODUCT_CSS_PATH.read_text(encoding="utf-8").lower()

    assert "--product-primary" in css
    assert "--product-secondary" in css
    assert "--bs-primary: var(--product-primary)" in css
    assert "--bs-secondary: var(--product-secondary)" in css
    assert '[data-bs-theme="light"]' in css
    assert '[data-bs-theme="dark"]' in css
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--product-focus-ring)" in css
    assert _contrast_ratio("#1d4ed8", "#ffffff") >= 4.5
    assert _contrast_ratio("#93c5fd", "#1f1f1f") >= 4.5


def test_duralux_uses_system_fonts_without_external_font_downloads() -> None:
    css = PRODUCT_CSS_PATH.read_text(encoding="utf-8").lower()

    assert "--product-font-sans: system-ui" in css
    assert "@font-face" not in css
    assert "fonts.googleapis.com" not in css


def test_only_allowlisted_application_assets_are_in_static_storage() -> None:
    expected = {
        "duralux/css/bootstrap.min.css",
        "duralux/css/theme.min.css",
        "duralux/css/product-integration.css",
        "duralux/images/favicon.svg",
        "duralux/images/logo_header.webp",
        "duralux/images/logo_login.webp",
        "duralux/js/bootstrap.bundle.min.js",
        "duralux/js/product-shell.js",
    }
    promoted = {
        str(path.relative_to(STATIC_ROOT))
        for path in STATIC_ROOT.rglob("*")
        if path.is_file()
    }

    assert expected <= promoted
    assert not any(path.endswith(("index.html", "user.png")) for path in promoted)
    assert not any("logo-full" in path or "bg-main" in path for path in promoted)
    for asset in expected:
        assert find(asset) is not None, f"Static finder cannot resolve {asset}"


def test_design_assets_are_application_owned() -> None:
    base_dir = Path(settings.BASE_DIR)
    source = base_dir / "design_system_duralux"

    assert source.is_dir()
    assert PRODUCT_CSS_PATH.is_file()
    assert find("duralux/css/product-integration.css") is not None
    assert not (STATIC_ROOT / "vendor").exists()

    tool_config = (base_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in tool_config


def test_design_system_has_no_legacy_icon_font_dependency() -> None:
    css = PRODUCT_CSS_PATH.read_text(encoding="utf-8").lower()

    assert "@font-face" not in css
    assert not (STATIC_ROOT / "fonts").exists()
    assert "https://" not in css


def test_design_reference_requires_authentication(client: Client) -> None:
    response = client.get(reverse("design_system_reference"))

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/admin/login/")


def test_design_reference_rejects_authenticated_non_staff(client: Client) -> None:
    user = UserFactory.create(is_staff=False)
    clinic = ClinicFactory.create()
    ClinicMembershipFactory.create(user=user, clinic=clinic)
    client.force_login(user)

    response = client.get(
        reverse("design_system_reference"),
        headers={"X-Clinic-ID": str(clinic.pk)},
    )

    assert response.status_code == 403


def test_design_reference_uses_normal_tenant_resolution(client: Client) -> None:
    user = UserFactory.create(is_staff=True)
    client.force_login(user)

    response = client.get(reverse("design_system_reference"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Selecione uma clínica para continuar."


def test_design_reference_is_pt_br_accessible_and_demo_free(client: Client) -> None:
    user, clinic = _staff_with_clinic()
    client.force_login(user)

    response = client.get(
        reverse("design_system_reference"),
        headers={"X-Clinic-ID": str(clinic.pk)},
    )
    content = response.content.decode("utf-8")
    lowered = content.lower()

    assert response.status_code == 200
    assert '<html lang="pt-BR"' in content
    assert "Referência do sistema visual" in content
    assert "Fundação Duralux" in content
    assert "Bootstrap" in content
    assert "aria-label=" in content
    assert 'aria-hidden="true"' in content
    assert "não depende apenas da cor" in lowered
    assert "rótulos visíveis" in lowered
    assert "john doe" not in lowered
    assert "dashboard" not in lowered
    assert "logo-dark.svg" not in lowered

    assert "/static/duralux/css/bootstrap.min.css" in content
    assert "/static/duralux/css/theme.min.css" in content
    assert "/static/duralux/css/product-integration.css" in content
