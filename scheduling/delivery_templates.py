"""Neutral reminder and message delivery text with no sensitive content.

These templates accept only non-clinical inputs (service name, appointment
time, sender name) so that a lock screen can never reveal mood, responses,
exercises or any health condition.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


def _local_time(value: datetime, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.get_current_timezone()
    return value.astimezone(tz)


def appointment_reminder_message(
    *, service_name: str, start_at: datetime, tz_name: str
) -> str:
    """Return a neutral appointment reminder with date/time only."""
    local = _local_time(start_at, tz_name)
    return (
        f"Lembrete: sua consulta de {service_name} está marcada para "
        f"{local.strftime('%d/%m/%Y às %H:%M')}."
    )


def new_message_notification_message(*, sender_name: str) -> str:
    """Return a neutral new-message notice without reproducing message content."""
    return f"Você tem uma nova mensagem de {sender_name} na plataforma."
