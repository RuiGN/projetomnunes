"""Acceptance tests for PRD 8.9 — dashboards e relatórios MVP."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from accounts.models import User
from accounts.services import accept_invitation
from analytics import services as analytics_services
from analytics.models import Report
from clinics.models import Clinic, ClinicMembership
from goals.exercise_models import (
    ExerciseAssignment,
    ExerciseExecution,
    TherapeuticExercise,
)
from goals.models import Goal
from journal.models import (
    CheckInQuestionnaire,
    DailyCheckIn,
    JournalEntry,
)
from people import services as people_services
from people.models import CareRelationship, PatientProfile
from scheduling.models import Appointment, Service, Unit
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _payload(email: str) -> dict[str, Any]:
    return {
        "full_name": "Paciente Exemplo",
        "social_name": "",
        "birth_date": date(1990, 1, 1),
        "gender": "undisclosed",
        "email": email,
        "phone": "",
        "language_code": "pt-BR",
        "timezone_name": "America/Sao_Paulo",
        "accessibility_preferences": "",
        "address": {},
        "address_purpose": "",
        "emergency_contact": {},
        "emergency_contact_purpose": "",
    }


def _linked_patient(
    clinic: Clinic, *, email: str = "um@example.test"
) -> tuple[User, User, PatientProfile]:
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=administrator, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    profile = people_services.register_patient_profile(
        clinic_id=clinic.pk, actor=administrator, request_id=uuid4(), **_payload(email)
    )
    issued = people_services.issue_patient_invitation(
        clinic_id=clinic.pk,
        actor=administrator,
        patient_profile_id=profile.pk,
        expires_at=people_services.invitation_expiration_after(days=2),
        request_id=uuid4(),
    )
    user = accept_invitation(
        raw_token=issued.raw_token,
        password="senha-sintetica-longa-e-nao-reutilizavel",
        first_name="Paciente",
        last_name="Exemplo",
    )
    profile.refresh_from_db()
    return administrator, user, profile


def _link_therapist(
    clinic: Clinic, administrator: User, profile: PatientProfile
) -> User:
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    people_services.create_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=administrator,
        therapist_id=therapist.pk,
        patient_profile_id=profile.pk,
        function="primary_therapist",
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    return therapist


def _service(clinic: Clinic) -> Service:
    return Service.infrastructure_objects.create(
        clinic_id=clinic.pk,
        name="Sessão individual",
        duration_minutes=50,
        buffer_minutes=10,
    )


def _unit(clinic: Clinic) -> Unit:
    return Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade Centro", timezone_name="America/Sao_Paulo"
    )


def _period() -> tuple[date, date]:
    end = dj_timezone.localdate()
    return end - timedelta(days=30), end


def _journal_entry(
    clinic: Clinic, patient: User, profile: PatientProfile, mood: int, visibility: str
) -> JournalEntry:
    return JournalEntry.infrastructure_objects.create(
        clinic_id=clinic.pk,
        author_id=patient.pk,
        patient_profile_id=profile.pk,
        mood=mood,
        emotions=[],
        intensity=3,
        context="Registro de teste",
        visibility=visibility,
    )


def _checkin(
    clinic: Clinic,
    patient: User,
    profile: PatientProfile,
    questionnaire: CheckInQuestionnaire,
    visibility: str,
    day_offset: int = 0,
) -> DailyCheckIn:
    return DailyCheckIn.infrastructure_objects.create(
        clinic_id=clinic.pk,
        patient_profile_id=profile.pk,
        author_id=patient.pk,
        questionnaire_id=questionnaire.pk,
        questionnaire_version="v1.0",
        date=dj_timezone.localdate() - timedelta(days=day_offset),
        answers={},
        visibility=visibility,
        submitted_at=dj_timezone.now(),
    )


def _questionnaire(clinic: Clinic) -> CheckInQuestionnaire:
    return CheckInQuestionnaire.infrastructure_objects.create(
        clinic_id=clinic.pk, title="Check-in Diário", version="v1.0", questions=[]
    )


def _appointment(
    clinic: Clinic,
    service: Service,
    unit: Unit,
    professional: User,
    profile: PatientProfile,
    status: str,
    offset_days: int = 0,
) -> Appointment:
    start = dj_timezone.now() + timedelta(days=offset_days)
    return Appointment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        service_id=service.pk,
        professional_id=professional.pk,
        patient_profile_id=profile.pk,
        unit_id=unit.pk,
        start_at=start,
        end_at=start + timedelta(minutes=service.duration_minutes),
        status=status,
        idempotency_key=uuid4().hex,
        requested_by_id=professional.pk,
    )


def _force_client(client: Client, clinic: Clinic, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()


# ---------------------------------------------------------------------------
# 8.9.1 / 8.9.2 Patient dashboard
# ---------------------------------------------------------------------------


def test_patient_dashboard_known_dataset() -> None:
    """8.9.1.4: Aggregations match a known dataset for one patient."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    service = _service(clinic)
    unit = _unit(clinic)
    questionnaire = _questionnaire(clinic)

    _journal_entry(clinic, patient, profile, 1, "shareable")
    _journal_entry(clinic, patient, profile, 3, "private")
    _journal_entry(clinic, patient, profile, 5, "shareable")
    _checkin(clinic, patient, profile, questionnaire, "shareable", day_offset=0)
    _checkin(clinic, patient, profile, questionnaire, "private", day_offset=1)
    Goal.infrastructure_objects.create(
        clinic_id=clinic.pk,
        patient_profile_id=profile.pk,
        author_id=patient.pk,
        defining_actor_id=patient.pk,
        title="Meta ativa",
        status="active",
    )
    exercise = TherapeuticExercise.infrastructure_objects.create(
        clinic_id=clinic.pk,
        author_id=therapist.pk,
        title="Respiração",
        instructions="...",
    )
    assignment = ExerciseAssignment.infrastructure_objects.create(
        clinic_id=clinic.pk,
        exercise_id=exercise.pk,
        patient_profile_id=profile.pk,
        assigned_by_id=therapist.pk,
    )
    ExerciseExecution.infrastructure_objects.create(
        clinic_id=clinic.pk,
        assignment_id=assignment.pk,
        patient_profile_id=profile.pk,
        started_at=dj_timezone.now(),
        completed_at=dj_timezone.now(),
    )
    _appointment(clinic, service, unit, therapist, profile, "confirmed", offset_days=2)

    start, end = _period()
    data = analytics_services.patient_dashboard_metrics(
        clinic_id=clinic.pk, actor=patient, period_start=start, period_end=end
    )

    assert data.checkin_count == 2
    assert data.mood_distribution == (1, 0, 1, 0, 1)
    assert data.active_goals == 1
    assert data.completed_exercises == 1
    assert data.upcoming_appointments == 1


def test_patient_dashboard_empty_period() -> None:
    """8.9.1.4: Absence of data yields zeroes without inference."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)

    data = analytics_services.patient_dashboard_metrics(
        clinic_id=clinic.pk,
        actor=patient,
        period_start=date(2000, 1, 1),
        period_end=date(2000, 1, 31),
    )
    assert data.checkin_count == 0
    assert data.mood_distribution == (0, 0, 0, 0, 0)
    assert data.has_data is False


def test_patient_dashboard_requires_patient_role() -> None:
    """8.9.1.2: Non-patient actors cannot read patient metrics."""
    clinic = ClinicFactory.create()
    admin, _patient, _profile = _linked_patient(clinic)
    start, end = _period()
    with pytest.raises(PermissionDenied):
        analytics_services.patient_dashboard_metrics(
            clinic_id=clinic.pk, actor=admin, period_start=start, period_end=end
        )


# ---------------------------------------------------------------------------
# 8.9.3 Therapist dashboard and privacy exclusions
# ---------------------------------------------------------------------------


def test_therapist_dashboard_excludes_non_shareable_checkins() -> None:
    """8.9.1.3: Only Verde check-ins reach the therapist's activity view."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    questionnaire = _questionnaire(clinic)

    _checkin(clinic, patient, profile, questionnaire, "shareable", day_offset=0)
    _checkin(
        clinic, patient, profile, questionnaire, "confirmation_required", day_offset=1
    )
    _checkin(clinic, patient, profile, questionnaire, "private", day_offset=2)

    start, end = _period()
    data = analytics_services.therapist_dashboard_metrics(
        clinic_id=clinic.pk, actor=therapist, period_start=start, period_end=end
    )
    assert data.active_patients == 1
    assert [row.checkin_count for row in data.activity_rows] == [1]


def test_therapist_dashboard_requires_therapist_role() -> None:
    """8.9.3.4: Direct access by a non-therapist is denied."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    start, end = _period()
    with pytest.raises(PermissionDenied):
        analytics_services.therapist_dashboard_metrics(
            clinic_id=clinic.pk, actor=patient, period_start=start, period_end=end
        )


def test_therapist_dashboard_cross_clinic_denied() -> None:
    """8.9.3.4: A therapist from another clinic cannot read this clinic's data."""
    clinic_a = ClinicFactory.create()
    _admin_a, _patient_a, _profile_a = _linked_patient(clinic_a)

    clinic_b = ClinicFactory.create()
    admin_b, _patient_b, profile_b = _linked_patient(clinic_b, email="b@example.test")
    therapist_b = _link_therapist(clinic_b, admin_b, profile_b)

    start, end = _period()
    with pytest.raises(PermissionDenied):
        analytics_services.therapist_dashboard_metrics(
            clinic_id=clinic_a.pk, actor=therapist_b, period_start=start, period_end=end
        )


def test_therapist_dashboard_excludes_ended_link() -> None:
    """8.9.3.4: A closed care link removes the patient from the dashboard."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)

    relationship = CareRelationship.infrastructure_objects.get(
        clinic_id=clinic.pk, therapist_id=therapist.pk, patient_profile_id=profile.pk
    )
    people_services.close_patient_care_relationship(
        clinic_id=clinic.pk,
        actor=admin,
        relationship_id=relationship.pk,
        ended_on=date.today(),
        request_id=uuid4(),
    )

    start, end = _period()
    data = analytics_services.therapist_dashboard_metrics(
        clinic_id=clinic.pk, actor=therapist, period_start=start, period_end=end
    )
    assert data.active_patients == 0


# ---------------------------------------------------------------------------
# 8.9.4 Clinic operational panel
# ---------------------------------------------------------------------------


def test_clinic_panel_known_dataset() -> None:
    """8.9.4.4: Formulas match a reference dataset."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    service = _service(clinic)
    unit = _unit(clinic)

    for _ in range(10):
        _appointment(clinic, service, unit, therapist, profile, "completed")
    for _ in range(5):
        _appointment(clinic, service, unit, therapist, profile, "no_show")
    for _ in range(5):
        _appointment(clinic, service, unit, therapist, profile, "canceled")
    for _ in range(10):
        _appointment(clinic, service, unit, therapist, profile, "confirmed")

    start, end = _period()
    data = analytics_services.clinic_operational_metrics(
        clinic_id=clinic.pk, actor=admin, period_start=start, period_end=end
    )

    assert data.total_appointments == 30
    assert data.confirmed == 10
    assert data.completed == 10
    assert data.no_show == 5
    assert data.canceled == 5
    assert data.occupancy_rate == 66.7
    assert data.no_show_rate == 33.3


def test_clinic_panel_requires_admin() -> None:
    """8.9.4.4: Non-administrative profiles are denied."""
    clinic = ClinicFactory.create()
    admin, _patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    start, end = _period()
    with pytest.raises(PermissionDenied):
        analytics_services.clinic_operational_metrics(
            clinic_id=clinic.pk, actor=therapist, period_start=start, period_end=end
        )


def test_clinic_panel_anonymization_threshold() -> None:
    """8.9.4.2: Small cells are suppressed below the aggregation threshold."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    service = _service(clinic)
    unit = _unit(clinic)

    for _ in range(3):
        _appointment(clinic, service, unit, therapist, profile, "completed")

    start, end = _period()
    data = analytics_services.clinic_operational_metrics(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=start,
        period_end=end,
        min_threshold=5,
    )
    assert data.total_appointments == 3
    assert data.by_unit[0].count is None  # suppressed below threshold
    assert data.active_patients is None  # 1 linked patient < threshold


# ---------------------------------------------------------------------------
# 8.9.5 Reports and secure export
# ---------------------------------------------------------------------------


def test_individual_report_generate_and_download() -> None:
    """8.9.5.2: A patient generates and downloads their own individual report."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    start, end = _period()

    report = analytics_services.generate_individual_report(
        clinic_id=clinic.pk,
        actor=patient,
        period_start=start,
        period_end=end,
        request_id=uuid4(),
    )
    assert report.kind == "individual"
    assert report.download_key
    content = report.file.read().decode("utf-8")
    assert "Relatório individual" in content

    downloaded = analytics_services.authorize_report_download(
        clinic_id=clinic.pk,
        actor=patient,
        report_id=report.pk,
        download_key=report.download_key,
        request_id=uuid4(),
    )
    assert downloaded.downloaded_at is not None
    assert downloaded.downloaded_by_id == patient.pk


def test_report_download_expired() -> None:
    """8.9.5.4: Expired report links are rejected."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    start, end = _period()
    report = analytics_services.generate_individual_report(
        clinic_id=clinic.pk,
        actor=patient,
        period_start=start,
        period_end=end,
        request_id=uuid4(),
    )
    report.expires_at = dj_timezone.now() - timedelta(hours=1)
    report.save(update_fields=("expires_at", "updated_at"))

    with pytest.raises(PermissionDenied):
        analytics_services.authorize_report_download(
            clinic_id=clinic.pk,
            actor=patient,
            report_id=report.pk,
            download_key=report.download_key,
            request_id=uuid4(),
        )


def test_report_download_wrong_actor_denied() -> None:
    """8.9.5.2: Another actor cannot download someone else's individual report."""
    clinic = ClinicFactory.create()
    _admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, _admin, profile)
    start, end = _period()
    report = analytics_services.generate_individual_report(
        clinic_id=clinic.pk,
        actor=patient,
        period_start=start,
        period_end=end,
        request_id=uuid4(),
    )

    with pytest.raises(PermissionDenied):
        analytics_services.authorize_report_download(
            clinic_id=clinic.pk,
            actor=therapist,
            report_id=report.pk,
            download_key=report.download_key,
            request_id=uuid4(),
        )


def test_operational_report_requires_admin() -> None:
    """8.9.5.3: Only clinic administrators generate operational reports."""
    clinic = ClinicFactory.create()
    admin, _patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    start, end = _period()
    with pytest.raises(PermissionDenied):
        analytics_services.generate_operational_report(
            clinic_id=clinic.pk,
            actor=therapist,
            period_start=start,
            period_end=end,
            request_id=uuid4(),
        )


def test_operational_report_contains_no_free_text() -> None:
    """8.9.5.3: Operational report content holds aggregates, not patient text."""
    clinic = ClinicFactory.create()
    admin, patient, profile = _linked_patient(clinic)
    therapist = _link_therapist(clinic, admin, profile)
    service = _service(clinic)
    unit = _unit(clinic)
    _journal_entry(clinic, patient, profile, 2, "shareable")
    _appointment(clinic, service, unit, therapist, profile, "completed")
    start, end = _period()

    report = analytics_services.generate_operational_report(
        clinic_id=clinic.pk,
        actor=admin,
        period_start=start,
        period_end=end,
        request_id=uuid4(),
    )
    content = report.file.read().decode("utf-8")
    assert "Registro de teste" not in content  # journal free text never leaks
    assert "Relatório operacional" in content


# ---------------------------------------------------------------------------
# HTTP smoke tests
# ---------------------------------------------------------------------------


def test_patient_dashboard_http(client: Client) -> None:
    """8.9.2: The patient dashboard renders over HTTP."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    _force_client(client, clinic, patient)

    res = client.get(reverse("patient_dashboard"))
    assert res.status_code == 200
    assert "Minha evolução" in res.content.decode()
    assert "Distribuição de humor" in res.content.decode()


def test_report_list_and_download_http(client: Client) -> None:
    """8.9.5: A patient lists and downloads their report over HTTP."""
    clinic = ClinicFactory.create()
    _admin, patient, _profile = _linked_patient(clinic)
    _force_client(client, clinic, patient)

    start, end = _period()
    post = client.post(
        reverse("report_generate"),
        data={"period_start": start.isoformat(), "period_end": end.isoformat()},
    )
    assert post.status_code == 302

    report = Report.infrastructure_objects.get(clinic_id=clinic.pk)
    listing = client.get(reverse("report_list"))
    assert listing.status_code == 200
    assert "Relatório" in listing.content.decode()

    download = client.get(
        reverse("report_download", args=[report.pk]) + f"?key={report.download_key}"
    )
    assert download.status_code == 200
    body = b"".join(download.streaming_content)  # type: ignore[attr-defined]
    assert b"Relat" in body
