"""Theme, layout preference, and accessible chart contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from accounts.models import User
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


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


def _token(css: str, block_selector: str, name: str) -> str:
    block = re.search(
        rf"{re.escape(block_selector)}\s*{{(?P<body>.*?)}}", css, re.DOTALL
    )
    assert block is not None
    value = re.search(rf"{re.escape(name)}:\s*(#[0-9a-f]{{6}})", block.group("body"))
    assert value is not None
    return value.group(1)


def _login(client: Client) -> User:
    user = UserFactory.create()
    clinic = ClinicFactory.create(name="Clínica Preferências")
    ClinicMembershipFactory.create(user=user, clinic=clinic)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()
    return user


def test_theme_bootstrap_runs_before_styles_and_toggle_is_accessible(
    client: Client,
) -> None:
    _login(client)

    content = client.get(reverse("workspace_vertical")).content.decode("utf-8")

    bootstrap = content.index("js/theme.js")
    stylesheet = content.index("css/framework.css")
    assert bootstrap < stylesheet
    assert '<script src="/static/js/theme.js"></script>' in content
    assert "data-theme-toggle" in content
    assert 'aria-label="Alternar tema claro e escuro"' in content
    assert 'aria-live="polite"' in content


def test_theme_script_detects_system_persists_and_announces_changes() -> None:
    script = (Path(settings.BASE_DIR) / "static" / "js" / "theme.js").read_text(
        encoding="utf-8"
    )

    assert 'safeStorageGet("workspace-theme")' in script
    assert 'matchMedia("(prefers-color-scheme: dark)")' in script
    assert "document.documentElement.dataset.theme" in script
    assert 'safeStorageSet("workspace-theme"' in script
    assert 'dispatchEvent(new CustomEvent("themechange"' in script
    assert "Tema escuro ativado" in script
    assert "Tema claro ativado" in script
    assert 'addEventListener("alpine:init"' in script
    assert 'Alpine.store("theme"' in script


def test_layout_preference_defaults_to_vertical_and_persists_per_user(
    client: Client,
) -> None:
    user = _login(client)
    assert user.preferred_layout == User.Layout.VERTICAL

    response = client.post(
        reverse("workspace_layout_preference"),
        {"layout": "detached", "next": reverse("workspace_vertical")},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("workspace_detached")
    user.refresh_from_db()
    assert user.preferred_layout == User.Layout.DETACHED

    content = client.get(reverse("workspace_detached")).content.decode("utf-8")
    assert '<option value="detached" selected>' in content


def test_default_workspace_route_restores_the_saved_layout(client: Client) -> None:
    user = _login(client)
    user.preferred_layout = User.Layout.DETACHED
    user.save(update_fields=["preferred_layout"])

    response = client.get(reverse("workspace_vertical"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("workspace_detached")


def test_layout_preference_rejects_unknown_value_without_mutation(
    client: Client,
) -> None:
    user = _login(client)

    response = client.post(
        reverse("workspace_layout_preference"),
        {"layout": "unknown", "next": "https://attacker.invalid/"},
    )

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.preferred_layout == User.Layout.VERTICAL


@override_settings(DEFAULT_WORKSPACE_LAYOUT="detached")
def test_layout_default_is_administrable() -> None:
    assert User().preferred_layout == User.Layout.DETACHED


def test_chart_adapter_uses_semantic_theme_and_accessible_equivalent() -> None:
    script = (Path(settings.BASE_DIR) / "static" / "js" / "charts.js").read_text(
        encoding="utf-8"
    )

    assert "window.ApexCharts" in script
    assert "getComputedStyle" in script
    assert 'addEventListener("themechange"' in script
    assert "updateOptions" in script
    assert "prefers-reduced-motion" in script
    assert 'Intl.DateTimeFormat("pt-BR"' in script
    assert 'axisType === "datetime"' in script
    assert "responsive:" in script
    assert "aria-describedby" in script
    assert "data-chart-summary" in script
    assert "data-chart-table" in script
    assert "diagnóstico" not in script.casefold()


def test_visual_reference_chart_has_summary_table_and_local_vendor_asset(
    client: Client,
) -> None:
    user = _login(client)
    user.is_staff = True
    user.save(update_fields=["is_staff"])

    content = client.get(reverse("design_system_reference")).content.decode("utf-8")
    vendor = (
        Path(settings.BASE_DIR)
        / "static"
        / "vendor"
        / "apexcharts"
        / "apexcharts.min.js"
    )

    assert vendor.is_file()
    assert "Gráfico de registros operacionais" in content
    assert "data-chart-summary" in content
    assert "data-chart-table" in content
    assert "Registros por semana" in content
    assert "Semana 1" in content
    assert "Apenas registros agregados autorizados" in content
    assert "js/charts.js" in content


def test_workspace_theme_tokens_keep_text_and_surfaces_accessible() -> None:
    tokens = (
        (Path(settings.BASE_DIR) / "static" / "css" / "tokens.css")
        .read_text(encoding="utf-8")
        .lower()
    )
    workspace = (
        Path(settings.BASE_DIR) / "static" / "css" / "workspace.css"
    ).read_text(encoding="utf-8")

    light_link = _token(tokens, ":root", "--color-link")
    dark_link = _token(tokens, '[data-theme="dark"]', "--color-link")
    light_control_border = _token(tokens, ":root", "--color-control-border")
    dark_control_border = _token(
        tokens, '[data-theme="dark"]', "--color-control-border"
    )
    action = _token(tokens, ":root", "--color-brand-action")
    assert _contrast_ratio(light_link, "#ffffff") >= 4.5
    assert _contrast_ratio(dark_link, "#1f1f1f") >= 4.5
    assert _contrast_ratio("#ffffff", action) >= 4.5
    assert _contrast_ratio(light_control_border, "#ffffff") >= 3
    assert _contrast_ratio(dark_control_border, "#1f1f1f") >= 3
    assert "border: 1px solid var(--color-control-border)" in workspace
    assert "background: var(--color-brand-soft)" in workspace
    assert "background: var(--color-detached-surface)" in workspace
    assert "color: var(--color-link)" in workspace
    assert "background: var(--color-brand-action)" in workspace


def test_theme_storage_has_a_safe_system_fallback() -> None:
    script = (Path(settings.BASE_DIR) / "static" / "js" / "theme.js").read_text(
        encoding="utf-8"
    )

    assert "safeStorageGet" in script
    assert "safeStorageSet" in script
    assert "try {" in script
