"""Acceptance tests for PRD 8.10.2 — disponibilidade e horários de atuação."""

from __future__ import annotations

from datetime import date, time, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinics.models import Clinic, ClinicMembership
from scheduling.availability_services import (
    create_availability_block,
    create_availability_override,
    create_availability_pattern,
    deactivate_availability_pattern,
)
from scheduling.models import (
    Unit,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin_therapist_unit() -> tuple[Clinic, User, User, Unit]:
    clinic = ClinicFactory.create()
    admin = UserFactory.create()
    therapist = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic, user=admin, role=ClinicMembership.Role.CLINIC_ADMIN
    )
    ClinicMembershipFactory.create(
        clinic=clinic, user=therapist, role=ClinicMembership.Role.THERAPIST
    )
    unit = Unit.infrastructure_objects.create(
        clinic_id=clinic.pk, name="Unidade Centro", timezone_name="America/Sao_Paulo"
    )
    return clinic, admin, therapist, unit


def test_create_availability_pattern_requires_admin() -> None:
    clinic, _admin, therapist, unit = _admin_therapist_unit()
    with pytest.raises(PermissionDenied):
        create_availability_pattern(
            clinic_id=clinic.pk,
            actor=therapist,
            professional_id=therapist.pk,
            unit_id=unit.pk,
            room_id=None,
            weekday=0,
            start_time=time(9, 0),
            end_time=time(17, 0),
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


def test_create_availability_pattern_rejects_inactive_therapist() -> None:
    """8.10.2.3: availability rejects a professional without an active link."""
    clinic, admin, _therapist, unit = _admin_therapist_unit()
    outsider = UserFactory.create()
    with pytest.raises(ValidationError):
        create_availability_pattern(
            clinic_id=clinic.pk,
            actor=admin,
            professional_id=outsider.pk,
            unit_id=unit.pk,
            room_id=None,
            weekday=0,
            start_time=time(9, 0),
            end_time=time(17, 0),
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


def test_create_availability_pattern_audits() -> None:
    clinic, admin, therapist, unit = _admin_therapist_unit()
    pattern = create_availability_pattern(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        room_id=None,
        weekday=0,
        start_time=time(9, 0),
        end_time=time(17, 0),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            action="create",
            resource_type="availability_pattern",
            resource_id=str(pattern.pk),
        )
        .exists()
    )


def test_deactivate_availability_pattern() -> None:
    clinic, admin, therapist, unit = _admin_therapist_unit()
    pattern = create_availability_pattern(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        room_id=None,
        weekday=0,
        start_time=time(9, 0),
        end_time=time(17, 0),
        valid_from=date.today(),
        valid_until=None,
        request_id=uuid4(),
    )
    deactivated = deactivate_availability_pattern(
        clinic_id=clinic.pk, actor=admin, pattern_id=pattern.pk, request_id=uuid4()
    )
    assert deactivated.is_active is False


def test_create_availability_override() -> None:
    clinic, admin, therapist, unit = _admin_therapist_unit()
    override = create_availability_override(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        room_id=None,
        override_date=date.today() + timedelta(days=1),
        start_time=None,
        end_time=None,
        available=False,
        reason="Feriado",
        request_id=uuid4(),
    )
    assert override.available is False
    assert override.reason == "Feriado"


def test_create_availability_block() -> None:
    clinic, admin, therapist, unit = _admin_therapist_unit()
    start = timezone.now() + timedelta(days=1)
    block = create_availability_block(
        clinic_id=clinic.pk,
        actor=admin,
        professional_id=therapist.pk,
        unit_id=unit.pk,
        room_id=None,
        start_at=start,
        end_at=start + timedelta(hours=1),
        reason="Reunião",
        request_id=uuid4(),
    )
    assert block.reason == "Reunião"


def test_availability_cross_clinic_denied() -> None:
    """8.10.2.3: a unit from another clinic cannot be used for availability."""
    clinic_a, admin_a, therapist_a, unit_a = _admin_therapist_unit()
    clinic_b, admin_b, therapist_b, _unit_b = _admin_therapist_unit()
    with pytest.raises(ValidationError):
        create_availability_pattern(
            clinic_id=clinic_b.pk,
            actor=admin_b,
            professional_id=therapist_b.pk,
            unit_id=unit_a.pk,
            room_id=None,
            weekday=0,
            start_time=time(9, 0),
            end_time=time(17, 0),
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )
