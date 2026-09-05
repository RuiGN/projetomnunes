"""Theme, layout preference, and accessible chart contracts."""

from __future__ import annotations

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

    bootstrap = content.index("duralux/js/product-shell.js")
    stylesheet = content.index("duralux/css/bootstrap.min.css")
    assert bootstrap < stylesheet
    assert '<script src="/static/duralux/js/product-shell.js"></script>' in content
    assert "data-theme-toggle" in content
    assert 'aria-label="Alternar tema claro e escuro"' in content
    assert 'aria-live="polite"' in content


def test_theme_script_detects_system_persists_and_announces_changes() -> None:
    script = (
        Path(settings.BASE_DIR) / "static" / "duralux" / "js" / "product-shell.js"
    ).read_text(encoding="utf-8")

    assert 'safeStorageGet("product-theme")' in script
    assert 'matchMedia("(prefers-color-scheme: dark)")' in script
    assert "root.dataset.bsTheme" in script
    assert 'safeStorageSet("product-theme", next)' in script
    assert 'dispatchEvent(new CustomEvent("themechange"' in script
    assert 'next === "dark" ? "Tema escuro" : "Tema claro"' in script
    assert "window.Alpine" not in script


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
    script = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "js"
        / "visual-reference-charts.js"
    ).read_text(encoding="utf-8")

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
        / "duralux"
        / "vendors"
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
    assert "duralux/js/visual-reference-charts.js" in content


def test_workspace_theme_tokens_keep_text_and_surfaces_accessible() -> None:
    css = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "css"
        / "product-integration.css"
    ).read_text(encoding="utf-8").lower()

    assert _contrast_ratio("#1d4ed8", "#ffffff") >= 4.5
    assert _contrast_ratio("#93c5fd", "#1f1f1f") >= 4.5
    assert '[data-bs-theme="light"]' in css
    assert '[data-bs-theme="dark"]' in css
    assert "--bs-link-color: #1d4ed8" in css
    assert "--bs-link-color: #93c5fd" in css
    assert "border: 1px solid var(--bs-border-color)" in css
    assert "background: var(--bs-body-bg)" in css
    assert "color: var(--bs-body-color)" in css
    assert "--bs-btn-bg: var(--product-primary)" in css


def test_theme_storage_has_a_safe_system_fallback() -> None:
    script = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "js"
        / "product-shell.js"
    ).read_text(encoding="utf-8")

    assert "safeStorageGet" in script
    assert "safeStorageSet" in script
    assert "try {" in script
