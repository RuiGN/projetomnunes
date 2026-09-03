"""Read selectors for the therapist dashboard."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from consents.selectors import accepted_consent_subject_ids
from core.selectors import Selector as Selector
from people.selectors import LinkedPatientRow, linked_patients_for_therapist

__all__ = [
    "Selector",
    "TherapistDashboardSnapshot",
    "therapist_dashboard_snapshot",
]


@dataclass(frozen=True, slots=True)
class TherapistDashboardSnapshot:
    """Factual operational view for one authorized therapist."""

    active_patients: int
    new_links: int
    incomplete_registrations: int
    pending_consents: int
    patients: tuple[LinkedPatientRow, ...]
    registration_series: tuple[dict[str, object], ...]


def _registration_series(
    rows: tuple[LinkedPatientRow, ...], today: date
) -> tuple[dict[str, object], ...]:
    """Build six zero-filled calendar months of patient registrations."""
    counter: Counter[str] = Counter()
    for row in rows:
        counter[f"{row.created_at.year}-{row.created_at.month:02d}"] += 1
    labels: list[str] = []
    for offset in range(5, -1, -1):
        month = (today.year * 12 + today.month - 1 - offset) % 12 + 1
        year = (today.year * 12 + today.month - 1 - offset) // 12
        labels.append(f"{year}-{month:02d}")
    return tuple({"label": label, "count": counter.get(label, 0)} for label in labels)


def therapist_dashboard_snapshot(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> TherapistDashboardSnapshot:
    """Return one therapist's linked patients and factual readiness metrics."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="therapist",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    today = timezone.localdate()
    rows = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=actor.pk, on_date=today
    )
    subject_ids = {row.user_id for row in rows if row.user_id is not None}
    accepted = accepted_consent_subject_ids(
        clinic_id=clinic_id, subject_ids=subject_ids
    )
    pending_consents = len(subject_ids - accepted)
    new_links = sum(
        1 for row in rows if row.link_valid_from >= today - timedelta(days=30)
    )
    incomplete_registrations = sum(1 for row in rows if not row.phone)
    return TherapistDashboardSnapshot(
        active_patients=len(rows),
        new_links=new_links,
        incomplete_registrations=incomplete_registrations,
        pending_consents=pending_consents,
        patients=rows,
        registration_series=_registration_series(rows, today),
    )
