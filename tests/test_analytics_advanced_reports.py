"""Tests for advanced purpose-controlled reporting and CSV protection (PRD 8.19.4)."""

import pytest

from analytics.advanced_reporting import (
    apply_small_cell_suppression,
    build_aggregated_metric_matrix,
    export_tabular_csv,
    sanitize_formula_injection,
)
from analytics.metrics_dictionary import (
    MetricCategory,
    get_metric_definition,
)


def test_metric_dictionary_definitions_exist() -> None:
    metric = get_metric_definition("active_patients_count")
    assert metric is not None
    assert metric.category == MetricCategory.CLINICAL_OPERATIONS
    assert metric.small_cell_threshold == 5
    assert metric.owner_role == "clinical_director"

    attendance = get_metric_definition("session_attendance_rate")
    assert attendance is not None
    assert attendance.category == MetricCategory.PATIENT_ENGAGEMENT


def test_small_cell_suppression() -> None:
    # Any count between 1 and 4 must be suppressed to "< 5"
    assert apply_small_cell_suppression(1, threshold=5) == "< 5"
    assert apply_small_cell_suppression(3, threshold=5) == "< 5"
    assert apply_small_cell_suppression(4, threshold=5) == "< 5"

    # 0 or >= 5 must not be suppressed
    assert apply_small_cell_suppression(0, threshold=5) == 0
    assert apply_small_cell_suppression(5, threshold=5) == 5
    assert apply_small_cell_suppression(12, threshold=5) == 12


def test_build_aggregated_metric_matrix_respects_dimensions_and_suppression() -> None:
    matrix = build_aggregated_metric_matrix(
        dimensions={"period": "2026-03", "service_category": "psychotherapy"},
        raw_counts={"group_a": 12, "group_b": 3, "group_c": 0},
        threshold=5,
    )
    assert matrix["metrics"]["group_a"] == 12
    assert matrix["metrics"]["group_b"] == "< 5"
    assert matrix["metrics"]["group_c"] == 0
    assert matrix["suppression_applied"] is True

    # Rejection of unapproved dimensions
    with pytest.raises(ValueError, match="Dimensões não permitidas"):
        build_aggregated_metric_matrix(
            dimensions={"patient_ssn": "123456789"},
            raw_counts={"group_a": 10},
        )


def test_formula_injection_sanitization() -> None:
    # Spreadsheet formula starters must be prefixed with single quote
    assert sanitize_formula_injection("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert sanitize_formula_injection("+SUM(A1:A10)") == "'+SUM(A1:A10)"
    assert sanitize_formula_injection("-10+20") == "'-10+20"
    assert sanitize_formula_injection("@HYPERLINK('http://malicious.test')") == "'@HYPERLINK('http://malicious.test')"
    assert sanitize_formula_injection("Texto inofensivo") == "Texto inofensivo"
    assert sanitize_formula_injection(42) == "42"


def test_export_tabular_csv_escapes_formulas_and_outputs_valid_csv() -> None:
    headers = ["Nome", "Fórmula Teste", "Valor"]
    rows = [
        ["Paciente 1", "=SUM(A1:B1)", 100],
        ["Paciente 2", "+cmd.exe", 200],
        ["Paciente 3", "Texto normal", 300],
    ]
    csv_output = export_tabular_csv(headers=headers, rows=rows)
    lines = (
        csv_output.strip().split("\r\n")
        if "\r\n" in csv_output
        else csv_output.strip().split("\n")
    )

    assert len(lines) == 4
    assert "'=SUM(A1:B1)" in lines[1]
    assert "'+cmd.exe" in lines[2]
    assert "Texto normal" in lines[3]
