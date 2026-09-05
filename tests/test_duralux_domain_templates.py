"""Source contracts for Duralux domain-template migration (Sprints 5-8)."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

SPRINT5_TEMPLATES = (
    "scheduling/appointment_calendar.html",
    "scheduling/appointment_list.html",
    "scheduling/appointment_request.html",
    "scheduling/appointment_reschedule.html",
    "scheduling/conversation_create.html",
    "scheduling/conversation_detail.html",
    "scheduling/conversation_list.html",
    "scheduling/reminder_preferences.html",
    "scheduling/room_form.html",
    "scheduling/unit_form.html",
    "scheduling/unit_list.html",
    "scheduling/waitlist_form.html",
    "scheduling/waitlist_list.html",
    "finance/charge_list.html",
    "finance/service_price_form.html",
)

SPRINT6_TEMPLATES = (
    "consents/center.html",
    "consents/decision_error.html",
    "consents/partials/document_decision.html",
    "consents/revocation_error.html",
    "consents/revocation_work_error.html",
    "consents/revocation_work_queue.html",
    "journal/checkin_list.html",
    "journal/checkin_today.html",
    "journal/checkin_unavailable.html",
    "journal/detail.html",
    "journal/form.html",
    "journal/list.html",
    "journal/partials/calendar.html",
    "goals/detail.html",
    "goals/exercise_assign.html",
    "goals/exercise_catalog.html",
    "goals/exercise_execute.html",
    "goals/exercise_execution_detail.html",
    "goals/exercise_form.html",
    "goals/form.html",
    "goals/list.html",
    "goals/low_energy.html",
    "goals/patient_exercises.html",
)

SPRINT7_TEMPLATES = (
    "content/detail.html",
    "content/editorial_compare.html",
    "content/editorial_create.html",
    "content/editorial_detail.html",
    "content/editorial_index.html",
    "content/editorial_preview.html",
    "content/learning/certificate.html",
    "content/learning/certificate_verify.html",
    "content/learning/cohort_detail.html",
    "content/learning/course_detail.html",
    "content/learning/index.html",
    "content/learning/lesson_page.html",
    "content/learning/module_detail.html",
    "content/learning/quiz_detail.html",
    "content/learning/quiz_feedback.html",
    "content/learning/quiz_participate.html",
    "content/lesson_player.html",
    "content/library.html",
    "content/notifications.html",
    "content/recommendations.html",
    "content/reports.html",
)

SPRINT8_TEMPLATES = ("visual_reference/reference.html",)

PARTIALS = {
    "consents/partials/document_decision.html",
    "journal/partials/calendar.html",
    "content/lesson_player.html",
}

LEGACY_CLASS_TOKENS = {
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
    "document-summary",
    "page-title",
}


def _source(relative_path: str) -> str:
    return (Path(settings.BASE_DIR) / "templates" / relative_path).read_text(
        encoding="utf-8"
    )


def _class_tokens(source: str) -> set[str]:
    return {
        token
        for match in re.finditer(r'class=(["\'])(.*?)\1', source)
        for token in match.group(2).split()
    }


def _assert_migrated(relative_path: str) -> None:
    source = _source(relative_path)
    assert "style=" not in source, relative_path
    assert not re.search(r"<script(?![^>]*\bsrc=)", source), relative_path
    assert not (_class_tokens(source) & LEGACY_CLASS_TOKENS), relative_path
    assert "design_system_duralux/" not in source, relative_path
    if relative_path not in PARTIALS:
        assert "{% block title %}" in source or "<title>" in source, relative_path


def test_sprint5_templates_use_duralux_without_inline_or_legacy_visuals() -> None:
    for relative_path in SPRINT5_TEMPLATES:
        _assert_migrated(relative_path)


def test_sprint6_templates_use_duralux_without_inline_or_legacy_visuals() -> None:
    for relative_path in SPRINT6_TEMPLATES:
        _assert_migrated(relative_path)


def test_unconsumed_goal_placeholder_is_removed() -> None:
    template_root = Path(settings.BASE_DIR) / "templates"
    placeholder = template_root / "goals/placeholder.html"

    assert not placeholder.exists()
    for path in template_root.rglob("*.html"):
        assert "goals/placeholder.html" not in path.read_text(encoding="utf-8")


def test_sprint7_templates_use_duralux_without_inline_or_legacy_visuals() -> None:
    for relative_path in SPRINT7_TEMPLATES:
        _assert_migrated(relative_path)


def test_visual_reference_uses_only_the_duralux_foundation() -> None:
    for relative_path in SPRINT8_TEMPLATES:
        _assert_migrated(relative_path)
    source = _source("visual_reference/reference.html")
    assert "duralux/css/bootstrap.min.css" in source
    assert "duralux/css/theme.min.css" in source
    assert "duralux/css/product-integration.css" in source
    assert "css/framework.css" not in source
    assert "css/tokens.css" not in source
    assert "css/workspace.css" not in source


def test_public_certificate_uses_duralux_brand_favicon_and_css() -> None:
    source = _source("content/learning/certificate_verify.html")
    assert "duralux/images/favicon.svg" in source
    assert "duralux/images/logo_header.webp" in source
    assert "duralux/css/bootstrap.min.css" in source
    assert "duralux/css/theme.min.css" in source
    assert "duralux/css/product-integration.css" in source
    assert "css/framework.css" not in source
    assert "css/tokens.css" not in source


def test_calendar_keeps_week_cells_in_the_monthly_seven_column_grid() -> None:
    calendar = _source("journal/partials/calendar.html")
    integration_css = (
        Path(settings.BASE_DIR) / "static/duralux/css/product-integration.css"
    ).read_text(encoding="utf-8")

    assert 'class="calendar-week" role="row"' in calendar
    assert ".calendar-grid" in integration_css
    assert "grid-template-columns: repeat(7, minmax(0, 1fr))" in integration_css
    assert re.search(
        r"\.calendar-week\s*\{\s*display:\s*contents;\s*\}", integration_css
    )
    assert "@media (max-width: 767.98px)" in integration_css


def test_goal_sharing_statuses_have_visible_icon_and_explanatory_text() -> None:
    goal_form = _source("goals/form.html")
    execution_detail = _source("goals/exercise_execution_detail.html")

    for source in (goal_form, execution_detail):
        assert "product-visibility-status" in source
        assert 'aria-hidden="true"' in source

    for label, description in (
        ("Compartilhável", "Pode compartilhar com o profissional."),
        ("Confirmar antes", "Confirme antes de compartilhar com o profissional."),
        ("Privado", "Somente você pode ver este registro."),
    ):
        assert label in goal_form
        assert description in goal_form
        assert description in execution_detail


def test_sprint6_uses_bootstrap_card_structure_and_no_tailwind_tokens() -> None:
    unsupported_tokens = {"space-y-4", "rounded-lg", "prose"}

    for relative_path in SPRINT6_TEMPLATES:
        source = _source(relative_path)
        assert not (_class_tokens(source) & unsupported_tokens), relative_path

        class_sets = [
            set(match.group(2).split())
            for match in re.finditer(r'class=(["\'])(.*?)\1', source)
        ]
        card_count = sum("card" in classes for classes in class_sets)
        card_body_count = sum("card-body" in classes for classes in class_sets)
        assert card_body_count >= card_count, relative_path


def test_sprint6_choice_groups_use_the_accessible_widget_renderer() -> None:
    required_groups = {
        "journal/form.html": ("mood", "emotions", "visibility"),
        "goals/form.html": ("horizon", "priority", "visibility"),
    }

    for relative_path, field_names in required_groups.items():
        source = _source(relative_path)
        assert "{{ choice.tag }}" not in source, relative_path
        for field_name in field_names:
            assert f"form.{field_name}|accessible_widget" in source, (
                relative_path,
                field_name,
            )
