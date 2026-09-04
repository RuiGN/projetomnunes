"""Tests for responsible, opt-in, non-punitive gamification (PRD 8.17.4)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from communities.gamification_services import (
    log_self_care_milestone,
    opt_in_responsible_gamification,
    pause_responsible_gamification,
    purge_gamification_history,
    resume_responsible_gamification,
    seed_default_self_care_milestones,
)
from communities.selectors import get_gamification_summary_for_user
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Gamificação")


@pytest.fixture
def patient_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="paciente_gamificacao@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture(autouse=True)
def seed_milestones(db: Any) -> None:
    seed_default_self_care_milestones()


def test_gamification_disabled_by_default(
    clinic_fixture: Clinic, patient_user: Any
) -> None:
    # Selector returns None for non-opted-in users
    summary = get_gamification_summary_for_user(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert summary is None

    # Logging milestone must fail before explicit opt-in
    with pytest.raises(ValueError, match="Gamification is disabled"):
        log_self_care_milestone(
            clinic_id=clinic_fixture.id,
            user=patient_user,
            milestone_slug="copo-de-agua",
        )


def test_opt_in_and_log_self_care_milestone(
    clinic_fixture: Clinic, patient_user: Any
) -> None:
    profile = opt_in_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert profile.is_opted_in is True
    assert profile.is_paused is False

    progress, affirmation = log_self_care_milestone(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        milestone_slug="copo-de-agua",
    )
    assert progress.count_today == 1
    assert "cuidado com você" in affirmation

    summary = get_gamification_summary_for_user(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert summary is not None
    assert len(summary["recent_progress"]) == 1


def test_daily_cap_and_supportive_message(
    clinic_fixture: Clinic, patient_user: Any
) -> None:
    opt_in_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )

    # "momento-gentileza" has daily_cap = 1
    progress_1, _ = log_self_care_milestone(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        milestone_slug="momento-gentileza",
    )
    assert progress_1.count_today == 1

    # Second attempt hits daily cap with respectful, encouraging message
    progress_2, message = log_self_care_milestone(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        milestone_slug="momento-gentileza",
    )
    assert progress_2.count_today == 1
    assert "Você já atingiu o marco de hoje" in message
    assert "Descanse e celebre" in message


def test_pause_and_resume_normalizes_hiatus(
    clinic_fixture: Clinic, patient_user: Any
) -> None:
    opt_in_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )

    # Pause gamification
    paused_profile = pause_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert paused_profile.is_paused is True

    with pytest.raises(ValueError, match="currently paused"):
        log_self_care_milestone(
            clinic_id=clinic_fixture.id,
            user=patient_user,
            milestone_slug="copo-de-agua",
        )

    # Resume gamification
    resumed_profile = resume_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert resumed_profile.is_paused is False

    progress, _ = log_self_care_milestone(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        milestone_slug="copo-de-agua",
    )
    assert progress.count_today == 1


def test_immediate_history_purge(
    clinic_fixture: Clinic, patient_user: Any
) -> None:
    opt_in_responsible_gamification(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    log_self_care_milestone(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        milestone_slug="copo-de-agua",
    )

    # Purge history and opt-out immediately
    purged_count = purge_gamification_history(
        clinic_id=clinic_fixture.id,
        user=patient_user,
        opt_out=True,
    )
    assert purged_count == 1

    summary = get_gamification_summary_for_user(
        clinic_id=clinic_fixture.id,
        user=patient_user,
    )
    assert summary is None

