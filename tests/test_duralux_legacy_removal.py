"""Regression guards for definitive removal of the legacy visual runtime."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

LEGACY_STATIC_PATHS = (
    "css/framework.css",
    "css/tokens.css",
    "css/workspace.css",
    "fonts/cerebrisans-bold.woff",
    "fonts/cerebrisans-medium.woff",
    "fonts/cerebrisans-regular.woff",
    "fonts/cerebrisans-semibold.woff",
    "fonts/remixicon.ttf",
    "fonts/remixicon.woff",
    "fonts/remixicon.woff2",
    "vendor/alpine/alpine.csp.min.js",
    "vendor/alpine/alpine-3.14.1.min.js",
    "vendor/apexcharts/apexcharts.min.js",
    "js/charts.js",
    "js/form-behaviors.js",
    "js/lesson-player.js",
    "js/theme.js",
    "js/workspace-navigation.js",
)

FORBIDDEN_RUNTIME_REFERENCES = (
    "css/framework.css",
    "css/tokens.css",
    "css/workspace.css",
    "cerebrisans",
    "remixicon",
    "vendor/alpine",
    "data-cloak",
    "x-data",
    "x-show",
    "x-on:",
    "design_system_duralux/",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_legacy_visual_static_files_are_removed() -> None:
    static_root = Path(settings.BASE_DIR) / "static"
    for relative_path in LEGACY_STATIC_PATHS:
        assert not (static_root / relative_path).exists(), relative_path


def test_runtime_templates_reference_no_legacy_or_demo_source_paths() -> None:
    template_root = Path(settings.BASE_DIR) / "templates"
    for path in sorted(template_root.rglob("*.html")):
        source = _read(path).lower()
        for forbidden in FORBIDDEN_RUNTIME_REFERENCES:
            assert forbidden.lower() not in source, f"{path}: {forbidden}"


def test_base_loads_only_global_duralux_dependencies() -> None:
    base = _read(Path(settings.BASE_DIR) / "templates/layouts/base.html")
    assert "duralux/css/bootstrap.min.css" in base
    assert "duralux/vendors/css/feather.min.css" in base
    assert "duralux/css/theme.min.css" in base
    assert "duralux/css/product-integration.css" in base
    assert "duralux/js/bootstrap.bundle.min.js" in base
    assert "duralux/js/product-shell.js" in base
    assert "apexcharts" not in base.lower()
    assert "lesson-player" not in base.lower()
    for forbidden in FORBIDDEN_RUNTIME_REFERENCES:
        assert forbidden.lower() not in base.lower()


def test_page_plugins_are_scoped_to_their_consumers() -> None:
    dashboard = _read(
        Path(settings.BASE_DIR) / "templates/therapist_dashboard/home.html"
    )
    lesson = _read(
        Path(settings.BASE_DIR) / "templates/content/learning/lesson_page.html"
    )
    assert "duralux/vendors/apexcharts/apexcharts.min.js" in dashboard
    assert "duralux/js/dashboard-charts.js" in dashboard
    assert "duralux/js/lesson-player.js" in lesson


def test_form_behaviors_are_loaded_only_by_form_consumers() -> None:
    base = _read(Path(settings.BASE_DIR) / "templates/layouts/base.html")
    template_root = Path(settings.BASE_DIR) / "templates"

    assert "duralux/js/form-behaviors.js" not in base
    for relative_path in (
        "accounts/auth_form.html",
        "accounts/sessions.html",
        "clinics/setup.html",
        "goals/form.html",
        "journal/checkin_today.html",
        "journal/form.html",
        "scheduling/appointment_request.html",
        "scheduling/appointment_reschedule.html",
        "scheduling/conversation_create.html",
        "scheduling/reminder_preferences.html",
    ):
        assert "duralux/js/form-behaviors.js" in _read(template_root / relative_path)


def test_visual_reference_grid_items_can_shrink_on_mobile() -> None:
    css = _read(Path(settings.BASE_DIR) / "static/duralux/css/product-integration.css")

    assert ".product-page > section" in css
    assert "min-width: 0" in css


def test_active_product_prd_names_duralux_as_the_visual_source() -> None:
    source = _read(Path(settings.BASE_DIR) / "PRD.md")
    assert "Duralux" in source
    assert "static/duralux/css/" in source
    assert "static/duralux/js/" in source
    for forbidden in (
        "Sliced",
        "Tailwind",
        "Alpine",
        "Cerebri Sans",
        "Remix Icon",
        "design_system_duralux/",
        "framework.css",
        "tokens.css",
        "workspace.css",
    ):
        assert forbidden not in source, forbidden


def test_template_coverage_reconciles_baseline_and_migration_helpers() -> None:
    coverage = _read(
        Path(settings.BASE_DIR) / "docs/duralux/application-template-coverage.md"
    )

    assert "Baseline contabilizada: **95 templates**" in coverage
    assert "Templates atuais no disco: **97**" in coverage
    for helper in (
        "accounts/auth_base.html",
        "accounts/mfa_enroll.html",
        "components/duralux_field.html",
    ):
        assert helper in coverage
    assert "goals/placeholder.html" in coverage
    assert "removido" in coverage


def test_incompatible_visual_specs_are_explicitly_superseded() -> None:
    root = Path(settings.BASE_DIR)
    historical_docs = (
        "docs/superpowers/specs/2026-08-31-cards-tables-states-design.md",
        "docs/superpowers/specs/2026-08-31-sliced-tokens-assets-design.md",
        "docs/superpowers/specs/2026-08-31-layouts-design.md",
        "docs/superpowers/specs/2026-08-31-application-owned-design-assets.md",
        "docs/superpowers/plans/2026-08-31-application-owned-design-assets.md",
        "docs/superpowers/plans/2026-08-31-layouts.md",
        "docs/superpowers/plans/2026-08-31-sliced-tokens-assets.md",
        "docs/superpowers/plans/2026-08-31-cards-tables-states.md",
    )

    for relative_path in historical_docs:
        heading = "\n".join(_read(root / relative_path).splitlines()[:8]).lower()
        assert "status: superseded" in heading, relative_path
