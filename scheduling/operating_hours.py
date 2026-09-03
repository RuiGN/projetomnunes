"""Pure operating-hours helpers used to gate out-of-hours responses."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

WEEKDAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

DEFAULT_OUT_OF_HOURS_NOTICE = (
    "Estamos fora do horário de atendimento. Sua mensagem foi registrada e "
    "será respondida dentro do horário comercial. Este canal não atende "
    "emergências."
)


def _local_time(value: datetime, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.get_current_timezone()
    return value.astimezone(tz)


def within_operating_hours(
    *, weekly_hours: dict[str, list[dict[str, str]]], now: datetime, tz_name: str
) -> bool:
    """Return whether `now` falls inside the configured weekly intervals."""
    local = _local_time(now, tz_name)
    key = WEEKDAY_KEYS[local.weekday()]
    current = local.strftime("%H:%M")
    for interval in weekly_hours.get(key, []):
        start = interval.get("start", "")
        end = interval.get("end", "")
        if start and end and start <= current < end:
            return True
    return False


def out_of_hours_response(
    *,
    weekly_hours: dict[str, list[dict[str, str]]],
    now: datetime,
    tz_name: str,
    instructions: str,
) -> str | None:
    """Return the configured out-of-hours text, or None when inside hours."""
    if within_operating_hours(weekly_hours=weekly_hours, now=now, tz_name=tz_name):
        return None
    return instructions.strip() or DEFAULT_OUT_OF_HOURS_NOTICE
