"""Regression contracts for Sprint 4 Duralux template integration."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

SPRINT4_TEMPLATE_PATHS = (
    "workspace/home.html",
    "analytics/clinic_panel.html",
    "analytics/patient_dashboard.html",
    "analytics/report_list.html",
    "analytics/therapist_dashboard.html",
    "therapist_dashboard/home.html",
    "clinics/confirm_switch.html",
    "clinics/setup.html",
    "clinics/whitelabel_domains.html",
    "people/patient_detail.html",
    "people/patient_form.html",
    "people/patient_list.html",
    "people/professional_list.html",
    "onboarding/clinic_checklist.html",
    "onboarding/patient_onboarding.html",
)

LEGACY_CLASS_TOKENS = (
    "welcome-panel",
    "workspace-eyebrow",
    "workspace-intro",
    "shortcut-row",
    "primary-action",
    "link-action",
    "summary-card-grid",
    "summary-card",
    "summary-card-heading",
    "component-section",
    "responsive-table-wrapper",
    "responsive-table",
    "chart-container",
    "section-heading",
    "table-filter",
    "table-scroll",
    "table-actions",
    "pagination-status",
    "pagination-links",
    "content-card",
    "form-actions",
    "context-chip",
    "form-stack",
    "form-field",
    "field-error",
    "field-help",
    "mood-badge",
    "mood-neutral",
    "confirmation-actions",
    "breadcrumbs",
    "choice-group",
    "clinic-brand-preview",
    "detail-list",
    "destructive-action",
    "checklist",
    "checklist-mark",
    "sr-only",
    "document-summary",
    "page-title",
)


def _template_source(relative_path: str) -> str:
    return (Path(settings.BASE_DIR) / "templates" / relative_path).read_text(
        encoding="utf-8"
    )


def _class_tokens(source: str) -> set[str]:
    return {
        token
        for match in re.finditer(r'class=(["\'])(.*?)\1', source)
        for token in match.group(2).split()
    }


def test_sprint4_templates_use_product_classes_instead_of_inline_code() -> None:
    for relative_path in SPRINT4_TEMPLATE_PATHS:
        source = _template_source(relative_path)
        assert "{% block title %}" in source, relative_path
        assert "style=" not in source, relative_path
        assert not re.search(r"<script(?![^>]*\bsrc=)", source), relative_path
        legacy_tokens = _class_tokens(source) & set(LEGACY_CLASS_TOKENS)
        assert not legacy_tokens, f"{relative_path}: {sorted(legacy_tokens)}"


def test_keyboard_focus_outweighs_vendor_control_resets() -> None:
    css = (
        Path(settings.BASE_DIR) / "static/duralux/css/product-integration.css"
    ).read_text()
    selector = (
        ".product-workspace-body :is(a, button, input, select, textarea, "
        "[tabindex]):focus-visible"
    )
    assert selector in css


def test_workspace_text_uses_theme_foreground_for_inherited_labels() -> None:
    css = (
        Path(settings.BASE_DIR) / "static/duralux/css/product-integration.css"
    ).read_text()
    assert re.search(
        r"\.product-workspace-body\s*\{[^}]*\bcolor:\s*var\(--bs-body-color\)", css
    )


def test_shell_neutralizes_transitional_legacy_grid() -> None:
    css = (
        Path(settings.BASE_DIR) / "static/duralux/css/product-integration.css"
    ).read_text()
    assert re.search(r"\.product-shell\s*\{[^}]*display:\s*block", css)


def test_sprint4_children_do_not_nest_main_landmarks() -> None:
    for relative_path in SPRINT4_TEMPLATE_PATHS:
        if relative_path != "clinics/confirm_switch.html":
            assert "<main" not in _template_source(relative_path), relative_path


def test_therapist_dashboard_uses_local_progressive_chart_enhancement() -> None:
    source = _template_source("therapist_dashboard/home.html")
    chart_script = (
        Path(settings.BASE_DIR) / "static" / "duralux" / "js" / "dashboard-charts.js"
    )

    assert "duralux/js/dashboard-charts.js" in source
    assert 'id="registrations-chart"' in source
    assert "<caption>Cadastros por mês</caption>" in source
    assert 'class="table product-table"' in source
    assert chart_script.is_file()
    assert "duralux/vendors/apexcharts/apexcharts.min.js" in source
    assert "static/vendor/apexcharts" not in source
