"""Tests for habit and routine planning, recurrence, and occurrences (8.14.1)."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from django.core.exceptions import ValidationError

from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from routines import services
from routines.models import (
    HabitFrequency,
    HabitStatus,
    TimeOfDayWindow,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Rotinas Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic):
    user = UserFactory.create(email="paciente.rotina@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(test_clinic: Clinic, patient_user) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Rotina e Hábitos",
        birth_date=date(1992, 5, 10),
    )


@pytest.mark.django_db
def test_create_habits_and_routine_blocks(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Patients can create routine blocks and habits with flexible time windows."""
    block = services.create_routine_block(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        name="Ritual Matinal",
        time_window=TimeOfDayWindow.MORNING,
        start_time=time(7, 30),
        order=0,
    )
    assert block.name == "Ritual Matinal"
    assert block.time_window == TimeOfDayWindow.MORNING

    habit = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Beber 500ml de água",
        description="Hidratação ao acordar",
        frequency=HabitFrequency.DAILY,
        time_window=TimeOfDayWindow.MORNING,
        target_duration_minutes=5,
        routine_block_id=block.id,
    )
    assert habit.title == "Beber 500ml de água"
    assert habit.status == HabitStatus.ACTIVE
    assert habit.version == 1

    # Empty name should raise ValidationError
    with pytest.raises(ValidationError, match="Nome do bloco de rotina é obrigatório"):
        services.create_routine_block(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            name="   ",
        )


@pytest.mark.django_db
def test_reorder_routine_blocks(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Routine blocks can be reordered in the agenda without affecting past records."""
    b1 = services.create_routine_block(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        name="Bloco 1",
        order=0,
    )
    b2 = services.create_routine_block(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        name="Bloco 2",
        order=1,
    )

    reordered = services.reorder_routine_blocks(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        block_ids_ordered=[b2.id, b1.id],
    )
    assert reordered[0].id == b2.id
    assert reordered[0].order == 0
    assert reordered[1].id == b1.id
    assert reordered[1].order == 1


@pytest.mark.django_db
def test_idempotent_occurrence_generation_for_date(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Occurrences are generated idempotently avoiding duplicates."""
    habit_daily = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Meditação rápida",
        frequency=HabitFrequency.DAILY,
        active_days=[0, 1, 2, 3, 4, 5, 6],
    )
    habit_weekdays = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Alongamento pós-trabalho",
        frequency=HabitFrequency.WEEKDAYS,
        active_days=[0, 1, 2, 3, 4],
    )

    # Monday (weekday 0)
    monday = date(2026, 9, 7)
    assert monday.weekday() == 0

    occs_first_run = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=monday,
    )
    assert len(occs_first_run) == 2
    assert {o.habit_id for o in occs_first_run} == {
        habit_daily.id,
        habit_weekdays.id,
    }

    # Repeated run must not duplicate
    occs_second_run = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=monday,
    )
    assert len(occs_second_run) == 2
    assert {o.id for o in occs_first_run} == {o.id for o in occs_second_run}

    # Sunday (weekday 6) should only generate habit_daily
    sunday = date(2026, 9, 13)
    assert sunday.weekday() == 6
    occs_sunday = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=sunday,
    )
    assert len(occs_sunday) == 1
    assert occs_sunday[0].habit_id == habit_daily.id


@pytest.mark.django_db
def test_pause_and_resume_preserves_streak_autonomy(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Pausing a habit skips occurrence generation, removing streak pressure."""
    habit = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Leitura de 15 minutos",
        frequency=HabitFrequency.DAILY,
    )

    target_date = date(2026, 9, 8)

    # Pause until tomorrow
    paused_habit = services.pause_habit(
        clinic_id=test_clinic.id,
        habit_id=habit.id,
        paused_until=target_date + timedelta(days=2),
    )
    assert paused_habit.status == HabitStatus.PAUSED

    # Should not generate occurrence during pause window
    occs_during_pause = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=target_date,
    )
    assert len(occs_during_pause) == 0

    # Resume habit
    resumed = services.resume_habit(
        clinic_id=test_clinic.id,
        habit_id=habit.id,
    )
    assert resumed.status == HabitStatus.ACTIVE
    assert resumed.paused_until is None

    # Should generate occurrence now
    occs_after_resume = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=target_date,
    )
    assert len(occs_after_resume) == 1
    assert occs_after_resume[0].habit_id == habit.id
