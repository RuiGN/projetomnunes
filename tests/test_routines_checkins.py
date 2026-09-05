"""Tests for habit check-ins, audit history, trends, and LGPD (8.14.2)."""

from __future__ import annotations

from datetime import date

import pytest

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from routines import selectors, services
from routines.models import (
    CheckInStatus,
    Habit,
    HabitFrequency,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Check-in Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.checkin@test.org")
    ClinicMembershipFactory.create(
        clinic=test_clinic,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(test_clinic: Clinic, patient_user: User) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=test_clinic,
        user=patient_user,
        full_name="Paciente Check-in e Tendências",
        birth_date=date(1990, 8, 15),
    )


@pytest.mark.django_db
def test_record_habit_checkin_and_audit_history(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Check-ins record one effective status and maintain edit history."""
    habit = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Caminhada leve",
        frequency=HabitFrequency.DAILY,
    )
    assert habit.id is not None

    today = date(2026, 9, 3)
    occs = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=today,
    )
    assert len(occs) == 1
    occ = occs[0]

    # First check-in: COMPLETED
    checkin = services.record_habit_checkin(
        clinic_id=test_clinic.id,
        occurrence_id=occ.id,
        status=CheckInStatus.COMPLETED,
        intensity_level=3,
        duration_minutes_executed=20,
        notes="Dia agradável",
        actor_id=patient_user.id,
    )
    assert checkin.status == CheckInStatus.COMPLETED
    assert checkin.duration_minutes_executed == 20
    assert len(checkin.history) == 1
    assert checkin.history[0]["new_status"] == CheckInStatus.COMPLETED

    # Revision: edit to PARTIAL (e.g. walked only 10 minutes)
    revised = services.record_habit_checkin(
        clinic_id=test_clinic.id,
        occurrence_id=occ.id,
        status=CheckInStatus.PARTIAL,
        intensity_level=2,
        duration_minutes_executed=10,
        notes="Ajustando: caminhei 10 minutos por causa da chuva",
        actor_id=patient_user.id,
    )
    assert revised.id == checkin.id  # One effective record per occurrence
    assert revised.status == CheckInStatus.PARTIAL
    assert revised.duration_minutes_executed == 10
    assert len(revised.history) == 2
    assert revised.history[1]["previous_status"] == CheckInStatus.COMPLETED
    assert revised.history[1]["new_status"] == CheckInStatus.PARTIAL


@pytest.mark.django_db
def test_habit_trends_without_punitive_streak_language(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Trends reflect frequency and effort over selected periods neutrally."""
    habit = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Exercício de respiração",
        frequency=HabitFrequency.DAILY,
    )
    assert habit.id is not None

    d1 = date(2026, 9, 1)
    d2 = date(2026, 9, 2)
    d3 = date(2026, 9, 3)

    occ1 = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=d1,
    )[0]
    occ2 = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=d2,
    )[0]
    services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=d3,
    )

    services.record_habit_checkin(
        clinic_id=test_clinic.id,
        occurrence_id=occ1.id,
        status=CheckInStatus.COMPLETED,
        duration_minutes_executed=15,
    )
    services.record_habit_checkin(
        clinic_id=test_clinic.id,
        occurrence_id=occ2.id,
        status=CheckInStatus.SKIPPED,
    )
    # occ3 left unreported

    trends = selectors.habit_trends_for_period(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=d1,
        end_date=d3,
    )
    assert trends["total_scheduled"] == 3
    assert trends["completed"] == 1
    assert trends["skipped"] == 1
    assert trends["unreported"] == 1
    assert trends["completion_rate_percent"] == 33.3
    assert trends["total_minutes_spent"] == 15


@pytest.mark.django_db
def test_export_and_delete_patient_routine_data_under_lgpd(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Patients can export and erase their routine records with audit trail."""
    habit = services.create_habit(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        title="Pausa para chá",
    )
    assert habit.id is not None
    occ = services.generate_habit_occurrences_for_date(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        scheduled_date=date(2026, 9, 3),
    )[0]
    services.record_habit_checkin(
        clinic_id=test_clinic.id,
        occurrence_id=occ.id,
        status=CheckInStatus.COMPLETED,
    )

    # 1. Export
    exported = services.export_patient_routine_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
    )
    assert len(exported["habits"]) == 1
    assert exported["habits"][0]["title"] == "Pausa para chá"
    assert len(exported["checkins"]) == 1

    # 2. Deletion
    services.delete_patient_routine_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        actor_id=patient_user.id,
    )
    assert (
        Habit.objects.for_clinic(test_clinic.id)
        .filter(patient_profile_id=patient_profile.id)
        .count()
        == 0
    )

    # Audit verification
    audit_log = (
        AuditEvent.infrastructure_objects.filter(clinic_id=test_clinic.id)
        .order_by("-occurred_at")
        .first()
    )
    assert audit_log is not None
    assert audit_log.action == "routines.patient_data_deleted"
