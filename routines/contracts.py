"""Domain contracts and adapter protocols for routines and health telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SleepDataPoint:
    """Standardized external health record for a sleep interval."""

    external_record_id: str
    bedtime: datetime
    wake_time: datetime
    duration_minutes: int
    deep_sleep_minutes: int = 0
    rem_sleep_minutes: int = 0
    light_sleep_minutes: int = 0
    source_device: str = "apple_health"
    confidence_score: float = 1.0


@dataclass(frozen=True)
class SleepSyncResult:
    """Result of an external device sleep synchronization batch."""

    data_points: list[SleepDataPoint] = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False


class SleepDeviceAdapter(Protocol):
    """Protocol for external sleep telemetry adapters (e.g., Apple Health)."""

    def sync_sleep_records(
        self,
        *,
        user_identifier: str,
        cursor: str | None = None,
    ) -> SleepSyncResult:
        """Fetch incremental sleep records using cursor-based pagination."""
        ...


class FakeSleepDeviceAdapter:
    """In-memory test double for external sleep data synchronization."""

    def __init__(self, sample_records: list[SleepDataPoint] | None = None) -> None:
        self.sample_records = list(sample_records or [])
        self.call_history: list[dict[str, str | None]] = []

    def sync_sleep_records(
        self,
        *,
        user_identifier: str,
        cursor: str | None = None,
    ) -> SleepSyncResult:
        self.call_history.append({"user_identifier": user_identifier, "cursor": cursor})
        return SleepSyncResult(
            data_points=list(self.sample_records),
            next_cursor="cursor_end_of_batch",
            has_more=False,
        )


__all__ = [
    "FakeSleepDeviceAdapter",
    "SleepDataPoint",
    "SleepDeviceAdapter",
    "SleepSyncResult",
]
