"""Tests for sleep diary, midnight validation, wearable sync, and LGPD (8.14.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from routines import selectors, sleep_services
from routines.contracts import FakeSleepDeviceAdapter, SleepDataPoint
from routines.models import (
    SleepDeviceSyncRecord,
    SleepEntry,
    SleepProvenance,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Sono Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.sono@test.org")
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
        full_name="Paciente Diário de Sono",
        birth_date=date(1995, 11, 20),
    )


@pytest.mark.django_db
def test_sleep_diary_cross_midnight_validation(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Sleep records correctly validate and calculate duration crossing midnight."""
    bedtime = datetime(2026, 9, 2, 23, 15, tzinfo=UTC)
    wake_time = datetime(2026, 9, 3, 7, 30, tzinfo=UTC)

    entry = sleep_services.record_sleep_entry(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        reference_date=date(2026, 9, 3),
        bedtime=bedtime,
        wake_time=wake_time,
        perceived_quality=4,
        nap_duration_minutes=20,
        notes="Dormi bem após ler um livro",
    )
    # 8 hours and 15 minutes = 495 minutes
    assert entry.duration_minutes == 495
    assert entry.perceived_quality == 4
    assert entry.nap_duration_minutes == 20

    # Inverted times must be rejected
    with pytest.raises(
        ValidationError, match="Horário de despertar deve ser posterior"
    ):
        sleep_services.record_sleep_entry(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            reference_date=date(2026, 9, 3),
            bedtime=wake_time,
            wake_time=bedtime,
        )


@pytest.mark.django_db
def test_wearable_sleep_device_sync_adapter(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """External wearable devices sync sleep intervals idempotently."""
    dp1 = SleepDataPoint(
        external_record_id="apple_sleep_001",
        bedtime=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        wake_time=datetime(2026, 9, 2, 6, 45, tzinfo=UTC),
        duration_minutes=465,
        deep_sleep_minutes=90,
        rem_sleep_minutes=110,
        light_sleep_minutes=265,
        source_device="apple_health",
    )
    adapter = FakeSleepDeviceAdapter(sample_records=[dp1])

    synced_first = sleep_services.sync_external_sleep_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        adapter=adapter,
        user_identifier="user_device_sync_id",
    )
    assert len(synced_first) == 1
    assert synced_first[0].provenance == SleepProvenance.DEVICE_IMPORTED
    assert synced_first[0].duration_minutes == 465

    # Re-running sync must be idempotent
    synced_second = sleep_services.sync_external_sleep_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        adapter=adapter,
        user_identifier="user_device_sync_id",
    )
    assert len(synced_second) == 1
    assert synced_first[0].id == synced_second[0].id
    assert (
        SleepDeviceSyncRecord.objects.for_clinic(test_clinic.id)
        .filter(patient_profile_id=patient_profile.id)
        .count()
        == 1
    )


@pytest.mark.django_db
def test_sleep_trends_summary_provenance_separation(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Trends distinguish self-reported from imported sleep data without diagnosis."""
    # 1 self-reported entry
    sleep_services.record_sleep_entry(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        reference_date=date(2026, 9, 1),
        bedtime=datetime(2026, 8, 31, 23, 0, tzinfo=UTC),
        wake_time=datetime(2026, 9, 1, 7, 0, tzinfo=UTC),
        perceived_quality=4,
        provenance=SleepProvenance.SELF_REPORTED,
    )

    # 1 device-imported entry
    dp = SleepDataPoint(
        external_record_id="dev_002",
        bedtime=datetime(2026, 9, 1, 23, 30, tzinfo=UTC),
        wake_time=datetime(2026, 9, 2, 7, 30, tzinfo=UTC),
        duration_minutes=480,
    )
    sleep_services.sync_external_sleep_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        adapter=FakeSleepDeviceAdapter(sample_records=[dp]),
    )

    summary = selectors.sleep_trends_summary(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
    )
    assert summary["total_entries"] == 2
    assert summary["self_reported_count"] == 1
    assert summary["device_imported_count"] == 1
    assert summary["avg_duration_minutes"] == 480


@pytest.mark.django_db
def test_delete_imported_sleep_data_under_lgpd(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Patients can delete imported health data while preserving self-reported
    logs.
    """
    # Self-reported
    sleep_services.record_sleep_entry(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        reference_date=date(2026, 9, 1),
        bedtime=datetime(2026, 8, 31, 23, 0, tzinfo=UTC),
        wake_time=datetime(2026, 9, 1, 7, 0, tzinfo=UTC),
        provenance=SleepProvenance.SELF_REPORTED,
    )
    # Device-imported
    dp = SleepDataPoint(
        external_record_id="dev_003",
        bedtime=datetime(2026, 9, 1, 23, 30, tzinfo=UTC),
        wake_time=datetime(2026, 9, 2, 7, 30, tzinfo=UTC),
        duration_minutes=480,
    )
    sleep_services.sync_external_sleep_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        adapter=FakeSleepDeviceAdapter(sample_records=[dp]),
    )

    # Delete imported data
    sleep_services.delete_imported_sleep_data(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        actor_id=patient_user.id,
    )

    # Self-reported still exists
    assert (
        SleepEntry.objects.for_clinic(test_clinic.id)
        .filter(
            patient_profile_id=patient_profile.id,
            provenance=SleepProvenance.SELF_REPORTED,
        )
        .count()
        == 1
    )
    # Imported is deleted
    assert (
        SleepEntry.objects.for_clinic(test_clinic.id)
        .filter(
            patient_profile_id=patient_profile.id,
            provenance=SleepProvenance.DEVICE_IMPORTED,
        )
        .count()
        == 0
    )

    # Audit event logged
    audit = (
        AuditEvent.infrastructure_objects.filter(clinic_id=test_clinic.id)
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.action == "routines.imported_sleep_data_deleted"
