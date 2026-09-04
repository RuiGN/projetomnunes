"""Observability, Telemetry PHI redaction, SLO tracking and WCAG 2.2 AA validation.

PRD section 8.20.4.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

# Regex patterns for deterministic PII/PHI scrubbing
CPF_REGEX = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
BEARER_REGEX = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)

CLINICAL_PHI_PATTERNS = [
    re.compile(
        r"\b(?:diagn[oó]stico|cid-?10|hip[oó]tese\s+diagn[oó]stica)\b.*", re.IGNORECASE
    ),
    re.compile(
        r"\b(?:prescri[çc][ãa]o|posologia|clonazepam|sertralina|fluoxetina)\b.*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ideao\s+suicida|autoles[ãa]o|tentativa\s+de\s+suic[íi]dio)\b.*",
        re.IGNORECASE,
    ),
]

SENSITIVE_KEY_SUBSTRINGS = frozenset(
    {"password", "secret", "token", "authorization", "api_key", "credentials", "cookie"}
)


class TelemetryRedactionEngine:
    """Central redaction engine ensuring zero PHI or credentials in telemetry."""

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        if not text:
            return ""
        sanitized = CPF_REGEX.sub("[REDACTED_CPF]", text)
        sanitized = EMAIL_REGEX.sub("[REDACTED_EMAIL]", sanitized)
        sanitized = BEARER_REGEX.sub("[REDACTED_BEARER_TOKEN]", sanitized)

        for pat in CLINICAL_PHI_PATTERNS:
            sanitized = pat.sub("[REDACTED_CLINICAL_PHI]", sanitized)
        return sanitized

    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            sanitized_dict: dict[str, Any] = {}
            for k, v in data.items():
                lower_key = str(k).lower()
                if any(sub in lower_key for sub in SENSITIVE_KEY_SUBSTRINGS):
                    sanitized_dict[k] = "[REDACTED_SECRET]"
                else:
                    sanitized_dict[k] = cls.sanitize_payload(v)
            return sanitized_dict
        elif isinstance(data, list):
            return [cls.sanitize_payload(item) for item in data]
        elif isinstance(data, str):
            return cls.sanitize_text(data)
        return data

    @classmethod
    def inject_correlation_context(
        cls, telemetry_event: dict[str, Any]
    ) -> dict[str, Any]:
        """Inject pseudonymous correlation IDs (trace_id, span_id) and scrub event."""
        sanitized = cls.sanitize_payload(telemetry_event)
        if not isinstance(sanitized, dict):
            sanitized = {"data": sanitized}

        if "trace_id" not in sanitized:
            sanitized["trace_id"] = f"tr_{uuid4().hex[:16]}"
        if "span_id" not in sanitized:
            sanitized["span_id"] = f"sp_{uuid4().hex[:12]}"
        return sanitized


class SloTracker:
    """SLO attainment and error budget calculator for integration journeys."""

    # Production SLO thresholds
    TARGET_AVAILABILITY = 0.999  # 99.9%
    TARGET_P95_LATENCY_MS = 300  # <= 300 ms
    TARGET_WEBHOOK_DELIVERY = 0.995  # 99.5%
    TARGET_OFFLINE_SYNC = 0.999  # 99.9%

    @classmethod
    def evaluate_journey_slos(
        cls,
        *,
        total_requests: int,
        failed_requests: int,
        p95_latency_ms: float,
        total_webhooks: int,
        failed_webhooks: int,
        total_syncs: int,
        failed_syncs: int,
    ) -> dict[str, Any]:
        """Compute attainment, error budgets and alerting status."""
        availability = (
            (total_requests - failed_requests) / total_requests
            if total_requests > 0
            else 1.0
        )
        webhook_delivery = (
            (total_webhooks - failed_webhooks) / total_webhooks
            if total_webhooks > 0
            else 1.0
        )
        sync_success = (
            (total_syncs - failed_syncs) / total_syncs if total_syncs > 0 else 1.0
        )

        # Allowed error rates
        allowed_api_error_rate = 1.0 - cls.TARGET_AVAILABILITY  # 0.001 (0.1%)
        actual_api_error_rate = 1.0 - availability

        # Remaining error budget percentage
        if actual_api_error_rate <= 0:
            error_budget_pct = 100.0
        elif actual_api_error_rate >= allowed_api_error_rate:
            error_budget_pct = 0.0
        else:
            error_budget_pct = (
                (allowed_api_error_rate - actual_api_error_rate)
                / allowed_api_error_rate
            ) * 100.0

        is_availability_met = availability >= cls.TARGET_AVAILABILITY
        is_latency_met = p95_latency_ms <= cls.TARGET_P95_LATENCY_MS
        is_webhook_met = webhook_delivery >= cls.TARGET_WEBHOOK_DELIVERY
        is_sync_met = sync_success >= cls.TARGET_OFFLINE_SYNC

        all_slos_met = (
            is_availability_met and is_latency_met and is_webhook_met and is_sync_met
        )

        return {
            "all_slos_met": all_slos_met,
            "availability": {
                "achieved": round(availability * 100, 3),
                "target": round(cls.TARGET_AVAILABILITY * 100, 2),
                "met": is_availability_met,
            },
            "latency": {
                "achieved_p95_ms": p95_latency_ms,
                "target_max_ms": cls.TARGET_P95_LATENCY_MS,
                "met": is_latency_met,
            },
            "webhook_delivery": {
                "achieved": round(webhook_delivery * 100, 3),
                "target": round(cls.TARGET_WEBHOOK_DELIVERY * 100, 2),
                "met": is_webhook_met,
            },
            "offline_sync": {
                "achieved": round(sync_success * 100, 3),
                "target": round(cls.TARGET_OFFLINE_SYNC * 100, 2),
                "met": is_sync_met,
            },
            "error_budget_remaining_percentage": round(error_budget_pct, 2),
            "exhausted_error_budget": error_budget_pct <= 0.0,
        }


class A11yValidator:
    """Automated validator for WCAG 2.2 AA accessibility requirements."""

    @classmethod
    def validate_component(cls, component_spec: dict[str, Any]) -> dict[str, Any]:
        violations: list[str] = []

        # 1. Color contrast check
        contrast_ratio = component_spec.get("contrast_ratio", 4.5)
        is_large_text = component_spec.get("is_large_text", False)
        min_contrast = 3.0 if is_large_text else 4.5
        if contrast_ratio < min_contrast:
            violations.append(
                f"Contrast ratio {contrast_ratio:.2f} is below WCAG AA requirement "
                f"of {min_contrast}:1"
            )

        # 2. Keyboard navigability
        is_interactive = component_spec.get("is_interactive", False)
        if is_interactive:
            if not component_spec.get("keyboard_navigable", True):
                violations.append("Interactive component is not keyboard navigable.")
            if not component_spec.get("focus_visible", True):
                violations.append("Focus indicator is not visible.")

            # 3. Touch target size (min 24x24, recommended 44x44)
            target_width = component_spec.get("target_width_px", 44)
            target_height = component_spec.get("target_height_px", 44)
            if target_width < 24 or target_height < 24:
                violations.append(
                    f"Target size {target_width}x{target_height}px is below "
                    "WCAG 2.2 min 24x24px"
                )

        # 4. Text alternative / ARIA
        has_text_content = bool(component_spec.get("text_content"))
        has_aria_label = bool(
            component_spec.get("aria_label") or component_spec.get("aria_labelledby")
        )
        if is_interactive and not has_text_content and not has_aria_label:
            violations.append(
                "Interactive element without text must have an aria-label."
            )

        # 5. Form inputs require associated label
        if (
            component_spec.get("element_type") == "input"
            and not component_spec.get("has_associated_label", False)
            and not has_aria_label
        ):
            violations.append(
                "Input field must have an associated <label> or aria-label."
            )

        return {
            "is_compliant": len(violations) == 0,
            "violations": violations,
            "standard": "WCAG 2.2 AA",
        }
