"""Protocols and adapters for external activity telemetry (8.15.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple, Protocol
from uuid import UUID


class ActivityDataPoint(NamedTuple):
    """External activity record from health wearable or sensor."""

    external_record_id: str
    activity_type: str
    start_time: datetime
    duration_minutes: int
    perceived_intensity: str = "moderate"
    rpe_scale: int = 4
    distance_meters: int | None = None
    metadata: dict[str, Any] = {}


class ActivityDeviceAdapter(Protocol):
    """Protocol for external activity telemetry adapters (Apple, Google, etc.)."""

    def sync_activity_records(
        self,
        *,
        clinic_id: UUID,
        patient_profile_id: UUID,
        sync_cursor: str = "",
    ) -> tuple[list[ActivityDataPoint], str]:
        """Fetch incremental activity records and new cursor."""
        ...


class FakeActivityDeviceAdapter:
    """In-memory adapter for testing wearable activity sync."""

    def __init__(self, data_points: list[ActivityDataPoint] | None = None) -> None:
        self.data_points = data_points or []

    def sync_activity_records(
        self,
        *,
        clinic_id: UUID,
        patient_profile_id: UUID,
        sync_cursor: str = "",
    ) -> tuple[list[ActivityDataPoint], str]:
        return list(self.data_points), f"cursor_{len(self.data_points)}"
