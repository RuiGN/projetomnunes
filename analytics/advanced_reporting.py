"""Purpose-controlled reporting and small-cell suppression (8.19.4)."""

from __future__ import annotations

import csv
import io
from enum import StrEnum
from typing import Any

DEFAULT_SMALL_CELL_THRESHOLD = 5


class ReportPurposeOfUse(StrEnum):
    """Permitted purposes of use under ABAC policy (PRD 8.19.4.2)."""

    CARE_MANAGEMENT = "care_management"
    HEALTH_OPERATIONS = "health_operations"
    LGPD_COMPLIANCE = "lgpd_compliance"
    QUALITY_AUDIT = "quality_audit"


ALLOWED_REPORT_DIMENSIONS: frozenset[str] = frozenset(
    {"period", "service_category", "status", "clinic_id"}
)


def sanitize_formula_injection(value: Any) -> str:
    """Neutralize formula injection characters in tabular exports (PRD 8.19.4.3).

    Prepends a single quote to strings starting with '=', '+', '-', '@', '\t', '\r'.
    """
    if not isinstance(value, str):
        return str(value)
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def apply_small_cell_suppression(
    count: int, threshold: int = DEFAULT_SMALL_CELL_THRESHOLD
) -> str | int:
    """Suppress aggregated cells with counts below threshold for privacy."""
    if 0 < count < threshold:
        return f"< {threshold}"
    return count


def build_aggregated_metric_matrix(
    *,
    dimensions: dict[str, str],
    raw_counts: dict[str, int],
    threshold: int = DEFAULT_SMALL_CELL_THRESHOLD,
) -> dict[str, Any]:
    """Assemble an aggregated report respecting dimensions and cell suppression."""
    unsupported = set(dimensions.keys()) - ALLOWED_REPORT_DIMENSIONS
    if unsupported:
        raise ValueError(
            f"Dimensões não permitidas: {unsupported}"
        )

    suppressed_counts: dict[str, str | int] = {}
    for key, count in raw_counts.items():
        suppressed_counts[key] = apply_small_cell_suppression(
            count, threshold=threshold
        )

    return {
        "dimensions": dimensions,
        "metrics": suppressed_counts,
        "suppression_applied": any(
            isinstance(v, str) and v.startswith("<") for v in suppressed_counts.values()
        ),
    }


def export_tabular_csv(headers: list[str], rows: list[list[Any]]) -> str:
    """Generate RFC 4180 CSV export with formula injection sanitization on all cells."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)

    sanitized_headers = [sanitize_formula_injection(h) for h in headers]
    writer.writerow(sanitized_headers)

    for row in rows:
        sanitized_row = [sanitize_formula_injection(cell) for cell in row]
        writer.writerow(sanitized_row)

    return buffer.getvalue()
