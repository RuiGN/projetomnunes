"""Acceptance tests for PRD 8.5.2 professional management."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from clinics import services as clinic_services
from clinics.models import Clinic, ClinicMembership
from people import models as people_models
from people import selectors as people_selectors
from people import services as people_services
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _admin_and_professional() -> tuple[Clinic, User, User]:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    professional = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=professional,
        role=ClinicMembership.Role.THERAPIST,
    )
    return clinic, administrator, professional


@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_admin_registers_complete_professional_profile_with_safe_photo_and_audit() -> (
    None
):
    clinic, administrator, professional = _admin_and_professional()
    photo = SimpleUploadedFile(
        "retrato-original.png",
        b"\x89PNG\r\n\x1a\n" + b"safe-profile-photo",
        content_type="image/png",
    )
    request_id = uuid4()

    profile = people_services.update_professional_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        user_id=professional.pk,
        full_name="Dra. Ana Exemplo",
        social_name="Ana",
        professional_email="ana.profissional@example.test",
        professional_phone="+55 11 99999-0000",
        photo=photo,
        biography="Atendimento psicológico para pessoas adultas.",
        accessibility_preferences="Prefere comunicação escrita.",
        category="psychologist",
        specialties=["anxiety", "adult_care"],
        council_name="CRP",
        council_number="00/000000",
        council_jurisdiction="SP",
        request_id=request_id,
    )

    assert isinstance(profile, people_models.ProfessionalProfile)
    assert profile.user_id == professional.pk
    assert profile.full_name == "Dra. Ana Exemplo"
    assert profile.social_name == "Ana"
    assert profile.professional_email == "ana.profissional@example.test"
    assert profile.professional_phone == "+55 11 99999-0000"
    assert profile.biography.startswith("Atendimento psicológico")
    assert profile.accessibility_preferences == "Prefere comunicação escrita."
    assert profile.category == "psychologist"
    assert profile.specialties == ["adult_care", "anxiety"]
    assert profile.council_name == "CRP"
    assert profile.council_number == "00/000000"
    assert profile.council_jurisdiction == "SP"
    assert profile.credential_status == "declared"
    assert "retrato-original" not in profile.photo.name
    assert profile.photo.name.startswith("professionals/")
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            actor_id=administrator.pk,
            action="update",
            resource_type="professional_profile",
            resource_id=str(profile.pk),
            outcome="success",
            request_id=request_id,
        )
        .exists()
    )


def test_declared_credentials_never_claim_automatic_verification() -> None:
    clinic, administrator, professional = _admin_and_professional()

    profile = people_services.update_professional_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        user_id=professional.pk,
        full_name="Ana Exemplo",
        social_name="",
        professional_email="ana@example.test",
        professional_phone="",
        photo=None,
        biography="",
        accessibility_preferences="",
        category="psychologist",
        specialties=["anxiety"],
        council_name="CRP",
        council_number="00/000000",
        council_jurisdiction="SP",
        request_id=uuid4(),
    )

    assert profile.credential_status == "declared"
    assert "verific" not in profile.get_credential_status_display().casefold()
    assert not hasattr(profile, "credentials_verified")


def test_admin_updates_professional_membership_metadata_and_authorizer() -> None:
    clinic, administrator, professional = _admin_and_professional()
    membership = ClinicMembership.objects.for_clinic(clinic.pk).get(user=professional)
    valid_from = date.today() + timedelta(days=1)
    valid_until = valid_from + timedelta(days=365)

    updated = clinic_services.update_professional_membership(
        clinic_id=clinic.pk,
        actor=administrator,
        membership_id=membership.pk,
        role=ClinicMembership.Role.THERAPIST,
        unit_name="Unidade Centro",
        valid_from=valid_from,
        valid_until=valid_until,
        request_id=uuid4(),
    )

    assert updated.unit_name == "Unidade Centro"
    assert updated.valid_from == valid_from
    assert updated.valid_until == valid_until
    assert updated.authorized_by_id == administrator.pk
    assert updated.professional_status(on_date=date.today()) == "scheduled"


def test_membership_update_denies_cross_tenant_identifier() -> None:
    clinic, administrator, _professional = _admin_and_professional()
    other_clinic = ClinicFactory.create()
    other_professional = UserFactory.create()
    other_membership = ClinicMembershipFactory.create(
        clinic=other_clinic,
        user=other_professional,
        role=ClinicMembership.Role.THERAPIST,
    )

    with pytest.raises(PermissionDenied):
        clinic_services.update_professional_membership(
            clinic_id=clinic.pk,
            actor=administrator,
            membership_id=other_membership.pk,
            role=ClinicMembership.Role.THERAPIST,
            unit_name="Unidade indevida",
            valid_from=date.today(),
            valid_until=None,
            request_id=uuid4(),
        )


def test_directory_filters_by_status_role_and_declared_specialty() -> None:
    clinic, administrator, professional = _admin_and_professional()
    people_services.update_professional_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        user_id=professional.pk,
        full_name="Ana Exemplo",
        social_name="",
        professional_email="ana@example.test",
        professional_phone="",
        photo=None,
        biography="",
        accessibility_preferences="",
        category="psychologist",
        specialties=["anxiety"],
        council_name="CRP",
        council_number="00/000000",
        council_jurisdiction="SP",
        request_id=uuid4(),
    )

    rows = people_selectors.professional_directory_visible_to(
        clinic_id=clinic.pk,
        actor=administrator,
        status="active",
        role="therapist",
        specialty="anxiety",
        on_date=date.today(),
    )

    assert len(rows) == 1
    assert rows[0].full_name == "Ana Exemplo"
    assert rows[0].specialties == ("anxiety",)


def test_admin_suspends_and_reactivates_professional_membership() -> None:
    clinic, administrator, professional = _admin_and_professional()
    membership = ClinicMembership.objects.for_clinic(clinic.pk).get(user=professional)

    suspended = clinic_services.suspend_professional_membership(
        clinic_id=clinic.pk,
        actor=administrator,
        membership_id=membership.pk,
        request_id=uuid4(),
    )
    assert suspended.professional_status(on_date=date.today()) == "suspended"

    reactivated = clinic_services.reactivate_professional_membership(
        clinic_id=clinic.pk,
        actor=administrator,
        membership_id=membership.pk,
        request_id=uuid4(),
    )
    assert reactivated.professional_status(on_date=date.today()) == "active"
    assert reactivated.authorized_by_id == administrator.pk


def test_professional_directory_http_is_accessible_and_permission_scoped(
    client: Client,
) -> None:
    clinic, administrator, professional = _admin_and_professional()
    people_services.update_professional_profile(
        clinic_id=clinic.pk,
        actor=administrator,
        user_id=professional.pk,
        full_name="Ana Exemplo",
        social_name="Ana",
        professional_email="ana@example.test",
        professional_phone="",
        photo=None,
        biography="",
        accessibility_preferences="",
        category="psychologist",
        specialties=["anxiety"],
        council_name="CRP",
        council_number="00/000000",
        council_jurisdiction="SP",
        request_id=uuid4(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("professional_list"), {"specialty": "anxiety"})

    content = response.content.decode()
    assert response.status_code == 200
    assert "Profissionais" in content
    assert "Ana Exemplo" in content
    assert "Convidar profissional" in content
    assert 'aria-label="Filtros de profissionais"' in content
    assert (
        reverse(
            "professional_suspend",
            args=[
                ClinicMembership.objects.for_clinic(clinic.pk).get(user=professional).pk
            ],
        )
        in content
    )
