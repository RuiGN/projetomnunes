"""Tests for activity tracking, device adapters, and overlap resolution (8.15.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory
from wellness import selectors, services
from wellness.contracts import ActivityDataPoint, FakeActivityDeviceAdapter
from wellness.models import (
    ActivityIntensity,
    ActivityLog,
    ActivityProvenance,
)


@pytest.fixture
def test_clinic() -> Clinic:
    return ClinicFactory.create(name="Clínica Atividade e Bem-estar Teste")


@pytest.fixture
def patient_user(test_clinic: Clinic) -> User:
    user = UserFactory.create(email="paciente.atividade@test.org")
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
        full_name="Paciente Atividade Física",
        birth_date=date(1993, 4, 12),
    )


@pytest.mark.django_db
def test_record_manual_activity_with_rpe_and_accessibility(
    test_clinic: Clinic, patient_profile: PatientProfile, patient_user: User
) -> None:
    """Manual activity records support duration, RPE, and assisted adaptations."""
    start = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

    # Invalid duration
    with pytest.raises(
        ValidationError, match="Duração da atividade deve ser maior que zero."
    ):
        services.record_activity(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            activity_type="Caminhada",
            start_time=start,
            duration_minutes=0,
        )

    # Invalid RPE
    with pytest.raises(
        ValidationError, match="Escala de esforço.*deve estar entre 1 e 10"
    ):
        services.record_activity(
            clinic_id=test_clinic.id,
            patient_profile_id=patient_profile.id,
            activity_type="Caminhada",
            start_time=start,
            duration_minutes=30,
            rpe_scale=11,
        )

    # Valid accessible & assisted activity
    log = services.record_activity(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        activity_type="Mobilidade em cadeira de rodas",
        start_time=start,
        duration_minutes=40,
        perceived_intensity=ActivityIntensity.MODERATE,
        rpe_scale=5,
        is_accessible_assisted=True,
        adaptations="Faixas elásticas de baixa resistência e apoio de postura",
        notes="Sessão confortável sem dor articular",
        actor_id=patient_user.id,
    )
    assert log.duration_minutes == 40
    assert log.is_accessible_assisted is True
    assert log.rpe_scale == 5
    assert log.provenance == ActivityProvenance.SELF_REPORTED

    # Audit event logged
    audit = (
        AuditEvent.infrastructure_objects.filter(
            clinic_id=test_clinic.id,
            action="wellness.activity_recorded",
        )
        .order_by("-occurred_at")
        .first()
    )
    assert audit is not None
    assert audit.resource_id == str(log.id)


@pytest.mark.django_db
def test_sync_external_wearable_activities_with_deduplication(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Wearable sync imports telemetry idempotently without duplicate records."""
    t1 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 2, 17, 30, tzinfo=UTC)

    dp1 = ActivityDataPoint(
        external_record_id="apple_act_001",
        activity_type="Corrida ao ar livre",
        start_time=t1,
        duration_minutes=35,
        distance_meters=5000,
        perceived_intensity=ActivityIntensity.VIGOROUS,
        rpe_scale=7,
    )
    dp2 = ActivityDataPoint(
        external_record_id="apple_act_002",
        activity_type="Alongamento",
        start_time=t2,
        duration_minutes=15,
        perceived_intensity=ActivityIntensity.LIGHT,
        rpe_scale=2,
    )

    adapter = FakeActivityDeviceAdapter(data_points=[dp1, dp2])
    sync_rec = services.sync_device_activities(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        device_provider="apple_health",
        adapter=adapter,
    )
    assert sync_rec.records_synced_count == 2
    assert sync_rec.sync_cursor == "cursor_2"
    assert (
        ActivityLog.objects.for_clinic(test_clinic.id)
        .filter(patient_profile_id=patient_profile.id)
        .count()
        == 2
    )

    # Re-syncing same data points does not duplicate records
    sync_rec_again = services.sync_device_activities(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        device_provider="apple_health",
        adapter=adapter,
    )
    assert sync_rec_again.records_synced_count == 2
    assert (
        ActivityLog.objects.for_clinic(test_clinic.id)
        .filter(patient_profile_id=patient_profile.id)
        .count()
        == 2
    )


@pytest.mark.django_db
def test_resolve_overlapping_activities_with_user_preference(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Consolidation marks overlapping events and honors user trend preference."""
    t_start = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)

    # Manual log
    manual = services.record_activity(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        activity_type="Caminhada",
        start_time=t_start,
        duration_minutes=30,
        provenance=ActivityProvenance.SELF_REPORTED,
    )

    # Device imported log for same period
    device = services.record_activity(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        activity_type="Caminhada",
        start_time=t_start,
        duration_minutes=32,
        distance_meters=2400,
        provenance=ActivityProvenance.DEVICE_IMPORTED,
        external_record_id="garmin_act_123",
    )

    # User chooses device record over manual record
    primary, secondary = services.resolve_overlapping_activities(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        primary_log_id=device.id,
        secondary_log_id=manual.id,
        prefer_primary=True,
    )
    assert primary.is_overlapping_consolidated is True
    assert primary.is_preferred_in_trends is True
    assert secondary.is_overlapping_consolidated is True
    assert secondary.is_preferred_in_trends is False

    # Original records remain preserved
    assert (
        ActivityLog.objects.for_clinic(test_clinic.id)
        .filter(patient_profile_id=patient_profile.id)
        .count()
        == 2
    )


@pytest.mark.django_db
def test_activity_trends_summary_includes_safety_disclaimer(
    test_clinic: Clinic, patient_profile: PatientProfile
) -> None:
    """Summary calculates volume and includes mandatory safety disclaimer."""
    d1 = date(2026, 9, 1)
    d2 = date(2026, 9, 3)

    services.record_activity(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        activity_type="Natação",
        start_time=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        duration_minutes=45,
        rpe_scale=6,
    )
    services.record_activity(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        activity_type="Alongamento adaptado",
        start_time=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        duration_minutes=20,
        rpe_scale=2,
        is_accessible_assisted=True,
    )

    trends = selectors.activity_trends_summary(
        clinic_id=test_clinic.id,
        patient_profile_id=patient_profile.id,
        start_date=d1,
        end_date=d2,
    )
    assert trends["total_sessions"] == 2
    assert trends["total_duration_minutes"] == 65
    assert trends["avg_duration_minutes"] == 32
    assert trends["avg_rpe_scale"] == 4.0
    assert trends["accessible_assisted_count"] == 1
    assert "Respeite seus limites individuais" in trends["safety_disclaimer"]
    assert "interrompa a atividade" in trends["safety_disclaimer"]
