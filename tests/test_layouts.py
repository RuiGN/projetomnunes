"""Tenant-safe contracts for vertical and detached workspace layouts."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountSession, User
from clinics.models import Clinic
from clinics.selectors import active_clinics_for_actor
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _login_with_two_clinics(client: Client) -> tuple[User, Clinic, Clinic]:
    user = UserFactory.create()
    current = ClinicFactory.create(name="Clínica Horizonte")
    target = ClinicFactory.create(name="Clínica Caminhos")
    ClinicMembershipFactory.create(user=user, clinic=current)
    ClinicMembershipFactory.create(user=user, clinic=target)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(current.pk)
    session.save()
    return user, current, target


def test_duralux_shell_css_has_responsive_drawer_and_brand_contract() -> None:
    css = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "css"
        / "product-integration.css"
    ).read_text(encoding="utf-8")

    for selector in (
        ".product-brand-logo",
        ".product-mobile-sidebar",
        ".product-drawer-overlay",
        ".product-scroll-locked",
    ):
        assert selector in css
    assert "@media (max-width: 991.98px)" in css
    assert "@media (max-width: 1199.98px)" in css
    assert "[data-sidebar-open]" in css
    assert "top: 0" in css
    assert '[data-bs-theme="dark"]' in css
    assert "--bs-heading-color: #f8fafc" in css
    assert "max-width: min(22rem, 92vw)" in css
    assert ".btn-secondary" in css
    assert "--bs-btn-color: #111827" in css
    assert "--bs-btn-hover-color: #111827" in css
    assert "outline: 3px solid var(--product-focus-ring)" in css
    assert "--product-focus-ring: #1d4ed8" in css
    assert "--product-focus-ring: #93c5fd" in css
    assert "[hidden]" in css
    assert ".product-auth-card" in css
    assert "max-width: 36rem" in css


def test_navigation_partial_uses_duralux_classes_without_legacy_shell_classes() -> None:
    navigation = (
        Path(settings.BASE_DIR)
        / "templates"
        / "layouts"
        / "partials"
        / "navigation.html"
    ).read_text(encoding="utf-8")

    assert 'class="nxl-navbar"' in navigation
    assert 'class="nxl-item"' in navigation
    assert 'class="nxl-link' in navigation
    assert 'class="nxl-micon"' in navigation
    assert 'class="nxl-mtext"' in navigation
    assert "navigation-list" not in navigation
    assert "navigation-section" not in navigation
    assert "navigation-link" not in navigation


def test_active_clinics_selector_returns_only_current_authorized_memberships() -> None:
    user = UserFactory.create()
    visible = ClinicFactory.create(name="Clínica Visível")
    inactive_clinic = ClinicFactory.create(is_active=False)
    expired = ClinicFactory.create()
    future = ClinicFactory.create()
    other = ClinicFactory.create()
    ClinicMembershipFactory.create(user=user, clinic=visible)
    ClinicMembershipFactory.create(user=user, clinic=inactive_clinic)
    ClinicMembershipFactory.create(
        user=user,
        clinic=expired,
        valid_from=date.today() - timedelta(days=30),
        valid_until=date.today() - timedelta(days=1),
    )
    ClinicMembershipFactory.create(
        user=user,
        clinic=future,
        valid_from=date.today() + timedelta(days=1),
    )
    ClinicMembershipFactory.create(clinic=other)

    assert active_clinics_for_actor(user) == [visible]


@pytest.mark.parametrize(
    ("route_name", "layout_label", "layout_class"),
    (
        ("workspace_vertical", "Navegação vertical", "layout-vertical"),
        ("workspace_detached", "Navegação destacada", "layout-detached"),
    ),
)
def test_workspace_layouts_share_semantics_and_authorized_context(
    client: Client,
    route_name: str,
    layout_label: str,
    layout_class: str,
) -> None:
    user, current, target = _login_with_two_clinics(client)

    response = client.get(reverse(route_name))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert 'lang="pt-BR"' in content
    assert f'class="{layout_class} product-shell' in content
    assert "Ir para o conteúdo principal" in content
    assert '<header class="nxl-header"' in content
    assert '<nav aria-label="Navegação principal"' in content
    assert '<div id="main-content"' in content
    assert '<nav aria-label="Caminho de navegação"' in content
    assert 'aria-current="page"' in content
    active_fragment = (
        'href="/workspace/" class="nxl-link is-active" aria-current="page"'
        if route_name == "workspace_vertical"
        else 'href="/workspace/detached/" class="nxl-link is-active" '
        'aria-current="page"'
    )
    assert active_fragment in content
    assert layout_label in content
    assert current.name in content
    assert target.name in content
    assert user.get_full_name() in content
    assert "Sliced" not in content
    assert "John Doe" not in content
    assert "Dashboard" not in content


def test_workspace_shell_uses_only_the_duralux_runtime(
    client: Client,
) -> None:
    _login_with_two_clinics(client)

    response = client.get(reverse("workspace_vertical"))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    for asset in (
        "/static/duralux/css/bootstrap.min.css",
        "/static/duralux/css/theme.min.css",
        "/static/duralux/css/product-integration.css",
        "/static/duralux/images/favicon.svg",
        "/static/duralux/images/logo_header.webp",
        "/static/duralux/js/bootstrap.bundle.min.js",
        "/static/duralux/js/product-shell.js",
        "/static/duralux/js/form-behaviors.js",
    ):
        assert asset in content
    for transitional_asset in (
        "/static/css/framework.css",
        "/static/css/tokens.css",
        "/static/css/workspace.css",
        "/static/js/form-behaviors.js",
        "/static/js/lesson-player.js",
        "/static/vendor/alpine/",
        "/static/vendor/apexcharts/",
        "/static/js/charts.js",
    ):
        assert transitional_asset not in content
    for legacy_attribute in ("x-data=", "x-show=", "x-ref="):
        assert legacy_attribute not in content
    assert 'class="nxl-navigation"' in content
    assert 'class="nxl-header"' in content
    assert 'class="nxl-container"' in content


def test_mobile_drawer_has_focus_escape_overlay_and_scroll_lock_contract(
    client: Client,
) -> None:
    _login_with_two_clinics(client)

    response = client.get(reverse("workspace_vertical"))
    content = response.content.decode("utf-8")
    script = (
        Path(settings.BASE_DIR) / "static" / "duralux" / "js" / "product-shell.js"
    ).read_text(encoding="utf-8")

    assert "data-mobile-sidebar" in content
    assert "data-sidebar-open" in content
    assert "data-sidebar-close" in content
    assert "data-sidebar-overlay" in content
    assert 'aria-controls="mobile-sidebar"' in content
    assert 'aria-modal="true"' in content
    assert "event.key === \"Escape\"" in script
    assert "event.key !== \"Tab\"" in script
    assert "product-scroll-locked" in script
    assert 'openButton?.setAttribute("aria-expanded", "true")' in script
    assert "closeButton?.focus()" in script
    assert "openButton?.focus()" in script


def test_mobile_drawer_closes_when_viewport_enters_desktop_mode() -> None:
    script = (
        Path(settings.BASE_DIR) / "static" / "duralux" / "js" / "product-shell.js"
    ).read_text(encoding="utf-8")

    assert 'window.matchMedia("(min-width: 1200px)")' in script
    assert 'desktopLayout.addEventListener("change"' in script
    assert "if (event.matches) closeSidebar();" in script


def test_product_shell_supports_accessible_local_text_copy() -> None:
    script = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "js"
        / "product-shell.js"
    ).read_text(encoding="utf-8")

    assert 'document.querySelectorAll("[data-copy-target]")' in script
    assert "navigator.clipboard.writeText" in script
    assert 'status.textContent = "Chave copiada."' in script
    assert (
        'status.textContent = "Não foi possível copiar. '
        'Selecione a chave manualmente."' in script
    )


def test_workspace_requires_authenticated_active_tenant(client: Client) -> None:
    anonymous = client.get(reverse("workspace_vertical"))
    assert anonymous.status_code == 302

    user = UserFactory.create()
    client.force_login(user)
    missing_context = client.get(reverse("workspace_vertical"))
    assert missing_context.status_code == 400


def test_switch_review_is_get_only_revalidates_and_does_not_mutate(
    client: Client,
) -> None:
    _, current, target = _login_with_two_clinics(client)

    response = client.get(
        reverse("clinic_switch_review"),
        {"clinic_id": str(target.pk), "next": reverse("workspace_vertical")},
    )

    assert response.status_code == 200
    assert current.name in response.content.decode("utf-8")
    assert target.name in response.content.decode("utf-8")
    assert client.session["active_clinic_id"] == str(current.pk)
    assert client.post(reverse("clinic_switch_review")).status_code == 405


def test_confirm_switch_reauthorizes_rotates_session_and_redirects_locally(
    client: Client,
) -> None:
    _, current, target = _login_with_two_clinics(client)
    old_session_key = client.session.session_key

    response = client.post(
        reverse("clinic_switch_confirm"),
        {"clinic_id": str(target.pk), "next": reverse("workspace_detached")},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("workspace_detached")
    assert client.session["active_clinic_id"] == str(target.pk)
    assert client.session.session_key != old_session_key
    assert str(current.pk) not in response.content.decode("utf-8")


def test_switch_preserves_tracked_session_under_fail_closed_validation(
    client: Client,
) -> None:
    _user, _current, target = _login_with_two_clinics(client)
    assert client.get(reverse("workspace_vertical")).status_code == 200
    old_tracking = AccountSession.objects.get(revoked_at__isnull=True)
    original_absolute_expiry = timezone.now() + timedelta(seconds=60)
    old_tracking.absolute_expires_at = original_absolute_expiry
    old_tracking.save(update_fields=("absolute_expires_at", "updated_at"))

    with override_settings(ACCOUNT_SESSION_ALLOW_UNKNOWN=False):
        response = client.post(
            reverse("clinic_switch_confirm"),
            {"clinic_id": str(target.pk), "next": reverse("workspace_vertical")},
        )
        workspace = client.get(reverse("workspace_vertical"))

    assert response.status_code == 302
    assert workspace.status_code == 200
    old_tracking.refresh_from_db()
    assert old_tracking.revoked_at is not None
    active_tracking = AccountSession.objects.get(revoked_at__isnull=True)
    assert active_tracking.absolute_expires_at == original_absolute_expiry


@pytest.mark.parametrize("target", ("not-a-uuid", "", None))
def test_switch_rejects_malformed_target_without_mutation(
    client: Client, target: str | None
) -> None:
    _, current, _ = _login_with_two_clinics(client)
    data = {} if target is None else {"clinic_id": target}

    response = client.post(reverse("clinic_switch_confirm"), data)

    assert response.status_code == 403
    assert client.session["active_clinic_id"] == str(current.pk)


def test_switch_rejects_other_inactive_or_expired_clinic(client: Client) -> None:
    user, current, _ = _login_with_two_clinics(client)
    unauthorized = ClinicFactory.create()
    inactive = ClinicFactory.create(is_active=False)
    expired = ClinicFactory.create()
    ClinicMembershipFactory.create(user=user, clinic=inactive)
    ClinicMembershipFactory.create(
        user=user,
        clinic=expired,
        valid_from=date.today() - timedelta(days=30),
        valid_until=date.today() - timedelta(days=1),
    )

    for clinic in (unauthorized, inactive, expired):
        response = client.post(
            reverse("clinic_switch_confirm"), {"clinic_id": str(clinic.pk)}
        )
        assert response.status_code == 403
        assert client.session["active_clinic_id"] == str(current.pk)


def test_switch_blocks_external_redirect(client: Client) -> None:
    _, _, target = _login_with_two_clinics(client)

    response = client.post(
        reverse("clinic_switch_confirm"),
        {"clinic_id": str(target.pk), "next": "https://malicious.example/collect"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("workspace_vertical")


def test_product_shell_replaces_alpine_without_demo_application_bundle() -> None:
    path = Path(settings.BASE_DIR) / "static" / "duralux" / "js" / "product-shell.js"
    content = path.read_text(encoding="utf-8")

    assert path.is_file()
    assert "data-sidebar-open" in content
    assert "data-theme-toggle" in content
    assert "localStorage" in content
    assert "window.Alpine" not in content
    assert "activeMenu" not in content
    assert "console.log" not in content
    assert "John Doe" not in content


def test_unknown_clinic_uuid_is_denied_without_enumeration(client: Client) -> None:
    _, current, _ = _login_with_two_clinics(client)

    response = client.post(
        reverse("clinic_switch_confirm"), {"clinic_id": str(uuid4())}
    )

    assert response.status_code == 403
    assert client.session["active_clinic_id"] == str(current.pk)


def test_sprint_three_account_and_error_templates_use_duralux_foundation() -> None:
    templates_root = Path(settings.BASE_DIR) / "templates"
    auth_base = (templates_root / "accounts" / "auth_base.html").read_text(
        encoding="utf-8"
    )
    title_fallback = (
        "{% if page_title %}{{ page_title }}"
        "{% else %}{{ title }}{% endif %}"
    )
    assert title_fallback in auth_base

    for relative_path in (
        "accounts/auth_form.html",
        "accounts/auth_message.html",
        "accounts/mfa_recovery_codes.html",
        "errors/400.html",
        "errors/403.html",
        "errors/404.html",
        "errors/500.html",
    ):
        template = (templates_root / relative_path).read_text(encoding="utf-8")
        assert '{% extends "accounts/auth_base.html" %}' in template
        assert 'class="product-auth-card' in template
        assert 'class="auth-card' not in template
        assert "primary-action" not in template

    sessions = (templates_root / "accounts" / "sessions.html").read_text(
        encoding="utf-8"
    )
    assert '{% extends "layouts/vertical.html" %}' in sessions
    assert 'class="card' in sessions
    assert 'class="btn btn-' in sessions
    assert "content-card" not in sessions
    assert "content-list" not in sessions
