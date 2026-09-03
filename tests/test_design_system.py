"""Contracts for the application-owned Sliced token and asset layer."""

from __future__ import annotations

import re
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
TOKENS_PATH = STATIC_ROOT / "css" / "tokens.css"
FRAMEWORK_PATH = STATIC_ROOT / "css" / "framework.css"

EXPECTED_LIGHT_TOKENS = {
    "--color-brand": "#6a69f5",
    "--color-success": "#50cd89",
    "--color-warning": "#ffc700",
    "--color-danger": "#f1416c",
    "--color-info": "#009ef7",
    "--color-text": "#151515",
    "--color-text-secondary": "#94989a",
    "--color-text-muted": "#6b7280",
    "--color-canvas": "#f9fbfd",
    "--color-surface": "#ffffff",
}
EXPECTED_DARK_TOKENS = {
    "--color-canvas": "#151515",
    "--color-surface": "#1f1f1f",
    "--color-border": "#323a46",
}


def _css_block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert match is not None, f"Missing CSS block: {selector}"
    return match.group("body").lower()


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


def test_semantic_palette_has_exact_light_and_dark_tokens() -> None:
    css = TOKENS_PATH.read_text(encoding="utf-8").lower()
    light = _css_block(css, ":root")
    dark = _css_block(css, '[data-theme="dark"]')

    for name, value in EXPECTED_LIGHT_TOKENS.items():
        assert f"{name}: {value}" in light
    for name, value in EXPECTED_DARK_TOKENS.items():
        assert f"{name}: {value}" in dark

    assert ":focus-visible" in css
    assert "outline: 3px solid var(--color-focus)" in css
    assert _contrast_ratio("#6b7280", "#f9fbfd") >= 4.5
    assert _contrast_ratio("#3533d8", "#ffffff") >= 4.5


def test_danger_text_token_meets_contrast_in_both_themes() -> None:
    tokens = TOKENS_PATH.read_text(encoding="utf-8").lower()
    workspace = (STATIC_ROOT / "css" / "workspace.css").read_text(encoding="utf-8")
    light = _css_block(tokens, ":root")
    dark = _css_block(tokens, '[data-theme="dark"]')

    assert "--color-danger-text: #b4234d" in light
    assert "--color-danger-text: #ff8dac" in dark
    assert _contrast_ratio("#b4234d", "#ffffff") >= 4.5
    assert _contrast_ratio("#ff8dac", "#1f1f1f") >= 4.5
    assert "color: var(--color-danger-text)" in workspace


def test_cerebri_sans_has_all_local_weights_and_swap_loading() -> None:
    css = TOKENS_PATH.read_text(encoding="utf-8").lower()

    assert css.count("@font-face") >= 5
    for filename, weight in (
        ("cerebrisans-regular.woff", "400"),
        ("cerebrisans-medium.woff", "500"),
        ("cerebrisans-semibold.woff", "600"),
        ("cerebrisans-bold.woff", "700"),
    ):
        assert (STATIC_ROOT / "fonts" / filename).is_file()
        assert f'url("../fonts/{filename}")' in css
        assert f"font-weight: {weight}" in css
    assert css.count("font-display: swap") >= 4
    assert 'font-family: "cerebri sans",' in css


def test_only_allowlisted_application_assets_are_in_static_storage() -> None:
    expected = {
        "css/tokens.css",
        "fonts/cerebrisans-bold.woff",
        "fonts/cerebrisans-medium.woff",
        "fonts/cerebrisans-regular.woff",
        "fonts/cerebrisans-semibold.woff",
        "fonts/remixicon.ttf",
        "fonts/remixicon.woff",
        "fonts/remixicon.woff2",
        "css/framework.css",
    }
    promoted = {
        str(path.relative_to(STATIC_ROOT))
        for path in STATIC_ROOT.rglob("*")
        if path.is_file()
    }

    assert expected <= promoted
    assert not any(path.endswith(("index.html", "user.png")) for path in promoted)
    assert not any("logo-" in path or "bg-main" in path for path in promoted)
    for asset in expected:
        assert find(asset) is not None, f"Static finder cannot resolve {asset}"


def test_design_assets_are_application_owned() -> None:
    base_dir = Path(settings.BASE_DIR)
    legacy_source_names = (
        "design" + "_system",
        "design" + "_system_v2",
    )

    assert FRAMEWORK_PATH.is_file()
    assert find("css/framework.css") is not None
    assert not (STATIC_ROOT / "vendor" / "sliced" / "main.css").exists()
    assert all(not (base_dir / name).exists() for name in legacy_source_names)

    tool_config = (base_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert all(name not in tool_config for name in legacy_source_names)


def test_remix_icon_is_local_and_has_accessible_usage_contract() -> None:
    css = TOKENS_PATH.read_text(encoding="utf-8").lower()
    for filename in ("remixicon.woff", "remixicon.woff2", "remixicon.ttf"):
        assert (STATIC_ROOT / "fonts" / filename).is_file()
    assert 'font-family: "remixicon"' in css
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
    assert "Cerebri Sans" in content
    assert "Remix Icon" in content
    assert "Tema claro" in content
    assert "Tema escuro" in content
    assert "aria-label=" in content
    assert 'aria-hidden="true"' in content
    assert "não depende apenas da cor" in lowered
    assert "contraste aa" in lowered
    assert ">Sliced<" not in content
    assert "john doe" not in lowered
    assert "dashboard" not in lowered
    assert "logo-dark.svg" not in lowered

    assert "/static/css/framework.css" in content
    assert "/static/css/tokens.css" in content
