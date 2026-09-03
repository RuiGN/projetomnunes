"""Read selectors for the journal domain."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.selectors import Selector as Selector
from people.selectors import linked_patients_for_therapist, patient_profile_for_user

from .models import (
    DailyCheckIn,
    HumanTriageItem,
    JournalAccessRequest,
    JournalEntry,
)

__all__ = [
    "CalendarDayData",
    "CalendarMonthData",
    "Selector",
    "patient_checkins",
    "patient_journal_calendar_data",
    "patient_journal_entries",
    "patient_pending_access_requests",
    "pending_triage_for_therapist",
    "therapist_visible_checkins",
    "therapist_visible_journal_entries",
]

MONTH_NAMES_PT_BR = (
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)

MOOD_LABELS = {
    1: "Muito mal",
    2: "Mal",
    3: "Neutro",
    4: "Bem",
    5: "Muito bem",
}

MOOD_CSS_CLASSES = {
    1: "mood-very-low",
    2: "mood-low",
    3: "mood-neutral",
    4: "mood-good",
    5: "mood-very-good",
}


@dataclass(frozen=True, slots=True)
class CalendarDayData:
    """One day's visual and accessible data in the emotional calendar."""

    date: date
    day_number: int
    is_current_month: bool
    is_today: bool
    entry_count: int
    dominant_mood: int | None
    dominant_mood_label: str
    mood_class: str
    accessible_label: str


@dataclass(frozen=True, slots=True)
class CalendarMonthData:
    """One month matrix for the emotional calendar with navigation metadata."""

    year: int
    month: int
    month_name: str
    previous_year: int
    previous_month: int
    next_year: int
    next_month: int
    days_header: Sequence[str]
    weeks: Sequence[Sequence[CalendarDayData]]
    legend: Sequence[tuple[int, str, str]]
    text_summary_rows: Sequence[tuple[str, str, int]]


def patient_journal_entries(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    period: str = "",
    emotion: str = "",
    mood: int | None = None,
) -> list[JournalEntry]:
    """Return filtered patient diary records in reverse chronological order."""
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        return []

    queryset = JournalEntry.objects.for_clinic(clinic_id).filter(
        patient_profile_id=profile.pk
    )

    today = timezone.localdate()
    if period == "7d":
        since = timezone.make_aware(
            datetime.combine(today - timedelta(days=7), time.min)
        )
        queryset = queryset.filter(created_at__gte=since)
    elif period == "30d":
        since = timezone.make_aware(
            datetime.combine(today - timedelta(days=30), time.min)
        )
        queryset = queryset.filter(created_at__gte=since)
    elif period == "90d":
        since = timezone.make_aware(
            datetime.combine(today - timedelta(days=90), time.min)
        )
        queryset = queryset.filter(created_at__gte=since)

    if mood is not None and mood in JournalEntry.Mood.values:
        queryset = queryset.filter(mood=mood)

    entries = list(queryset.order_by("-created_at", "-id"))

    if emotion and emotion in JournalEntry.Emotion.values:
        entries = [entry for entry in entries if emotion in (entry.emotions or [])]

    return entries


def patient_journal_calendar_data(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    year: int | None = None,
    month: int | None = None,
) -> CalendarMonthData:
    """Generate the calendar matrix and textual equivalent for one month."""
    today = timezone.localdate()
    current_year = year or today.year
    current_month = month or today.month

    if current_month < 1 or current_month > 12:
        current_month = today.month
    if current_year < 2000 or current_year > 2100:
        current_year = today.year

    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    entries_by_date: dict[date, list[JournalEntry]] = {}

    if profile is not None:
        _, num_days = calendar.monthrange(current_year, current_month)
        start_date = date(current_year, current_month, 1) - timedelta(days=7)
        end_date = date(current_year, current_month, num_days) + timedelta(days=7)

        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(end_date, time.max))

        entries = (
            JournalEntry.objects.for_clinic(clinic_id)
            .filter(
                patient_profile_id=profile.pk,
                created_at__gte=start_dt,
                created_at__lte=end_dt,
            )
            .order_by("created_at")
        )

        for entry in entries:
            entry_local_date = timezone.localtime(entry.created_at).date()
            entries_by_date.setdefault(entry_local_date, []).append(entry)

    cal = calendar.Calendar(firstweekday=6)  # Sunday as first day of week
    weeks_raw = cal.monthdatescalendar(current_year, current_month)

    weeks: list[list[CalendarDayData]] = []
    text_summary_rows: list[tuple[str, str, int]] = []

    for week_dates in weeks_raw:
        week_data: list[CalendarDayData] = []
        for d in week_dates:
            is_current_month = d.month == current_month
            is_today = d == today
            day_entries = entries_by_date.get(d, [])
            entry_count = len(day_entries)

            if entry_count > 0:
                dominant_mood = day_entries[-1].mood
                dominant_mood_label = MOOD_LABELS.get(dominant_mood, "Registrado")
                mood_class = MOOD_CSS_CLASSES.get(dominant_mood, "mood-neutral")
                accessible_label = (
                    f"{d.day} de {MONTH_NAMES_PT_BR[d.month]}: "
                    f"Humor {dominant_mood_label} ({dominant_mood}/5) — "
                    f"{entry_count} registro{'s' if entry_count > 1 else ''}"
                )
                if is_current_month:
                    formatted_date = f"{d.day:02d}/{d.month:02d}/{d.year}"
                    text_summary_rows.append(
                        (formatted_date, dominant_mood_label, entry_count)
                    )
            else:
                dominant_mood = None
                dominant_mood_label = "Sem registro"
                mood_class = "mood-empty"
                accessible_label = (
                    f"{d.day} de {MONTH_NAMES_PT_BR[d.month]}: Sem registros"
                )

            week_data.append(
                CalendarDayData(
                    date=d,
                    day_number=d.day,
                    is_current_month=is_current_month,
                    is_today=is_today,
                    entry_count=entry_count,
                    dominant_mood=dominant_mood,
                    dominant_mood_label=dominant_mood_label,
                    mood_class=mood_class,
                    accessible_label=accessible_label,
                )
            )
        weeks.append(week_data)

    if current_month == 1:
        prev_year = current_year - 1
        prev_month = 12
    else:
        prev_year = current_year
        prev_month = current_month - 1

    if current_month == 12:
        next_year = current_year + 1
        next_month = 1
    else:
        next_year = current_year
        next_month = current_month + 1

    legend = [
        (1, "Muito mal", "mood-very-low"),
        (2, "Mal", "mood-low"),
        (3, "Neutro", "mood-neutral"),
        (4, "Bem", "mood-good"),
        (5, "Muito bem", "mood-very-good"),
    ]

    return CalendarMonthData(
        year=current_year,
        month=current_month,
        month_name=f"{MONTH_NAMES_PT_BR[current_month]} de {current_year}",
        previous_year=prev_year,
        previous_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        days_header=("Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"),
        weeks=tuple(tuple(w) for w in weeks),
        legend=tuple(legend),
        text_summary_rows=tuple(text_summary_rows),
    )


def patient_pending_access_requests(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> list[JournalAccessRequest]:
    """Return pending therapist access requests for one patient."""
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        return []
    return list(
        JournalAccessRequest.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=profile.pk,
            status=JournalAccessRequest.Status.PENDING,
        )
        .select_related("therapist", "journal_entry")
        .order_by("-requested_at")
    )


def therapist_visible_journal_entries(
    *, clinic_id: UUID, therapist_id: UUID
) -> list[JournalEntry]:
    """Return only shareable or active granted records for therapist's patients.

    Private (Vermelho) records are NEVER returned under any circumstances.
    Confirmation-required (Amarelo) records are ONLY returned if there is an active,
    unexpired, non-revoked granted JournalAccessRequest for this therapist.
    """
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=therapist_id,
        role="therapist",
        on_date=today,
    ):
        raise PermissionDenied
    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=therapist_id, on_date=today
    )
    profile_ids = {row.patient_profile_id for row in linked}
    if not profile_ids:
        return []

    # 1. Shareable entries (Verde)
    shareable_entries = list(
        JournalEntry.objects.for_clinic(clinic_id).filter(
            patient_profile_id__in=profile_ids,
            visibility=JournalEntry.Visibility.SHAREABLE,
        )
    )

    # 2. Granted Yellow entries (Amarelo)
    now = timezone.now()
    granted_entry_ids = set(
        JournalAccessRequest.objects.for_clinic(clinic_id)
        .filter(
            therapist_id=therapist_id,
            status=JournalAccessRequest.Status.GRANTED,
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
        .values_list("journal_entry_id", flat=True)
    )

    granted_yellow_entries: list[JournalEntry] = []
    if granted_entry_ids:
        granted_yellow_entries = list(
            JournalEntry.objects.for_clinic(clinic_id).filter(
                id__in=granted_entry_ids,
                patient_profile_id__in=profile_ids,
                visibility=JournalEntry.Visibility.CONFIRMATION_REQUIRED,
            )
        )

    all_visible = shareable_entries + granted_yellow_entries
    all_visible.sort(key=lambda e: (e.created_at, e.id), reverse=True)
    return all_visible


def patient_checkins(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    since: datetime | None = None,
) -> list[DailyCheckIn]:
    """Return the patient's own submitted check-ins, newest first."""
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        return []
    queryset = DailyCheckIn.objects.for_clinic(clinic_id).filter(
        patient_profile_id=profile.pk,
        is_draft=False,
        submitted_at__isnull=False,
    )
    if since is not None:
        queryset = queryset.filter(submitted_at__gte=since)
    return list(queryset.order_by("-submitted_at", "-id"))


def therapist_visible_checkins(
    *,
    clinic_id: UUID,
    therapist_id: UUID,
    since: datetime | None = None,
) -> list[DailyCheckIn]:
    """Return only shareable check-ins for one therapist's linked patients.

    Private (Vermelho) and un-authorized Amarelo check-ins are never returned.
    """
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id, user_id=therapist_id, role="therapist", on_date=today
    ):
        raise PermissionDenied
    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=therapist_id, on_date=today
    )
    profile_ids = {row.patient_profile_id for row in linked}
    if not profile_ids:
        return []
    queryset = DailyCheckIn.objects.for_clinic(clinic_id).filter(
        patient_profile_id__in=profile_ids,
        visibility=JournalEntry.Visibility.SHAREABLE,
        is_draft=False,
        submitted_at__isnull=False,
    )
    if since is not None:
        queryset = queryset.filter(submitted_at__gte=since)
    return list(queryset.order_by("-submitted_at", "-id"))


def pending_triage_for_therapist(
    *, clinic_id: UUID, therapist_id: UUID
) -> list[HumanTriageItem]:
    """Return pending human-review triage items for one therapist's patients."""
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id, user_id=therapist_id, role="therapist", on_date=today
    ):
        raise PermissionDenied
    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=therapist_id, on_date=today
    )
    profile_ids = {row.patient_profile_id for row in linked}
    if not profile_ids:
        return []
    return list(
        HumanTriageItem.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id__in=profile_ids,
            status=HumanTriageItem.Status.PENDING,
        )
        .select_related("rule", "checkin")
        .order_by("-created_at")
    )
