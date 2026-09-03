"""Acceptance tests for PRD 8.5.1 clinic setup."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from accounts.models import User
from audit.models import AuditAction, AuditEvent, AuditOutcome
from clinics import forms as clinic_forms
from clinics import models as clinic_models
from clinics import services as clinic_services
from clinics.models import Clinic, ClinicMembership
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def _complete_operations(clinic: Clinic, administrator: User) -> None:
    clinic_services.update_clinic_operations(
        clinic_id=clinic.pk,
        actor=administrator,
        timezone_name="America/Sao_Paulo",
        language_code="pt-BR",
        service_channels=["in_person"],
        weekly_hours={day: [] for day, _label in clinic_forms.WEEKDAYS},
        out_of_hours_instructions="",
        request_id=uuid4(),
    )


def _complete_branding(clinic: Clinic, administrator: User) -> None:
    clinic_services.update_clinic_branding(
        clinic_id=clinic.pk,
        actor=administrator,
        logo=SimpleUploadedFile(
            "logo.png",
            b"\x89PNG\r\n\x1a\n" + b"safe-raster-content",
            content_type="image/png",
        ),
        primary_color="#1D4ED8",
        secondary_color="#93C5FD",
        request_id=uuid4(),
    )


def test_clinic_admin_records_tenant_scoped_institutional_identity() -> None:
    assert hasattr(clinic_models, "ClinicConfiguration")
    assert hasattr(clinic_services, "update_clinic_identity")
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    request_id = uuid4()

    configuration = clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Terapêutica Exemplo Ltda.",
        display_name="Clínica Exemplo",
        registration_identifier="00.000.000/0001-00",
        administrative_email="contato@example.test",
        administrative_phone="+55 11 4000-0000",
        address_line_1="Rua Exemplo, 100",
        address_line_2="Sala 4",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=request_id,
    )

    assert configuration.clinic_id == clinic.pk
    assert configuration.legal_name == "Clínica Terapêutica Exemplo Ltda."
    assert configuration.display_name == "Clínica Exemplo"
    assert configuration.registration_identifier == "00.000.000/0001-00"
    assert configuration.administrative_email == "contato@example.test"
    assert configuration.administrative_phone == "+55 11 4000-0000"
    assert configuration.address_line_1 == "Rua Exemplo, 100"
    assert configuration.address_line_2 == "Sala 4"
    assert configuration.city == "São Paulo"
    assert configuration.region == "SP"
    assert configuration.postal_code == "01000-000"
    assert configuration.country_code == "BR"
    assert (
        AuditEvent.objects.for_clinic(clinic.pk)
        .filter(
            actor_id=administrator.pk,
            action=AuditAction.UPDATE,
            resource_type="clinic_configuration",
            resource_id=str(configuration.pk),
            outcome=AuditOutcome.SUCCESS,
            request_id=request_id,
        )
        .exists()
    )


@pytest.mark.django_db
def test_clinic_admin_records_operational_context_and_hours() -> None:
    assert hasattr(clinic_services, "update_clinic_operations")
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Terapêutica Exemplo Ltda.",
        display_name="Clínica Exemplo",
        registration_identifier="00.000.000/0001-00",
        administrative_email="contato@example.test",
        administrative_phone="+55 11 4000-0000",
        address_line_1="Rua Exemplo, 100",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )

    configuration = clinic_services.update_clinic_operations(
        clinic_id=clinic.pk,
        actor=administrator,
        timezone_name="America/Sao_Paulo",
        language_code="pt-BR",
        service_channels=["in_person", "video"],
        weekly_hours={
            "monday": [{"start": "08:00", "end": "18:00"}],
            "tuesday": [{"start": "08:00", "end": "18:00"}],
            "wednesday": [{"start": "08:00", "end": "18:00"}],
            "thursday": [{"start": "08:00", "end": "18:00"}],
            "friday": [{"start": "08:00", "end": "17:00"}],
            "saturday": [],
            "sunday": [],
        },
        out_of_hours_instructions="Em urgência, procure o serviço público local.",
        request_id=uuid4(),
    )

    assert configuration.timezone_name == "America/Sao_Paulo"
    assert configuration.language_code == "pt-BR"
    assert configuration.service_channels == ["in_person", "video"]
    assert configuration.weekly_hours["friday"] == [{"start": "08:00", "end": "17:00"}]
    assert "urgência" in configuration.out_of_hours_instructions


@pytest.mark.django_db
@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_clinic_admin_uploads_safe_logo_and_contrasting_brand_colors() -> None:
    assert hasattr(clinic_services, "update_clinic_branding")
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Terapêutica Exemplo Ltda.",
        display_name="Clínica Exemplo",
        registration_identifier="",
        administrative_email="contato@example.test",
        administrative_phone="",
        address_line_1="Rua Exemplo, 100",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    logo = SimpleUploadedFile(
        "logo-da-clinica.png",
        b"\x89PNG\r\n\x1a\n" + b"safe-raster-content",
        content_type="image/png",
    )

    configuration = clinic_services.update_clinic_branding(
        clinic_id=clinic.pk,
        actor=administrator,
        logo=logo,
        primary_color="#1D4ED8",
        secondary_color="#93C5FD",
        request_id=uuid4(),
    )

    assert configuration.logo.name.startswith(f"clinics/{clinic.pk}/branding/")
    assert "logo-da-clinica" not in configuration.logo.name
    assert configuration.primary_color == "#1D4ED8"
    assert configuration.secondary_color == "#93C5FD"


@pytest.mark.django_db
def test_clinic_admin_enables_modules_with_prerequisites_and_authorship() -> None:
    assert hasattr(clinic_services, "update_clinic_modules")
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Terapêutica Exemplo Ltda.",
        display_name="Clínica Exemplo",
        registration_identifier="",
        administrative_email="contato@example.test",
        administrative_phone="",
        address_line_1="Rua Exemplo, 100",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )

    configuration = clinic_services.update_clinic_modules(
        clinic_id=clinic.pk,
        actor=administrator,
        enabled_modules=["patient_management", "clinical_records", "agenda"],
        request_id=uuid4(),
    )

    assert configuration.enabled_modules == [
        "agenda",
        "clinical_records",
        "patient_management",
    ]
    assert configuration.modules_updated_by_id == administrator.pk
    assert configuration.modules_updated_at is not None


@pytest.mark.django_db
def test_clinic_setup_is_primary_navigation_action_for_admin(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("workspace_vertical"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Configurar clínica" in content
    assert 'href="/clinics/setup/"' in content


@pytest.mark.django_db
def test_clinic_setup_form_enables_shared_duplicate_submission_guard(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("clinic_setup"))

    content = response.content.decode()
    assert "data-form-guard" in content
    assert "data-submit-button" in content


@pytest.mark.django_db
def test_clinic_setup_rejects_skipping_incomplete_stages(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("clinic_setup") + "?stage=review")

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("clinic_setup") + "?stage=identity"


@pytest.mark.django_db
def test_clinic_setup_blocks_module_post_before_operations(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica HTTP Ltda.",
        display_name="Clínica HTTP",
        registration_identifier="",
        administrative_email="admin@clinic.example",
        administrative_phone="",
        address_line_1="Rua Segura, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("clinic_setup"),
        {"stage": "modules", "enabled_modules": ["patient_management"]},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("clinic_setup") + "?stage=operations"
    configuration = clinic_models.ClinicConfiguration.objects.for_clinic(
        clinic.pk
    ).get()
    assert configuration.enabled_modules == []


@pytest.mark.django_db
def test_identity_stage_posts_to_active_tenant_and_advances(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("clinic_setup"),
        {
            "stage": "identity",
            "legal_name": "Clínica HTTP Ltda.",
            "display_name": "Clínica HTTP",
            "registration_identifier": "",
            "administrative_email": "admin@clinic.example",
            "administrative_phone": "+55 11 4000-0000",
            "address_line_1": "Rua Segura, 10",
            "address_line_2": "",
            "city": "São Paulo",
            "region": "SP",
            "postal_code": "01000-000",
            "country_code": "BR",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('clinic_setup')}?stage=operations"
    configuration = clinic_models.ClinicConfiguration.objects.for_clinic(
        clinic.pk
    ).get()
    assert configuration.display_name == "Clínica HTTP"


@pytest.mark.django_db
def test_operations_stage_posts_hours_and_advances(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica HTTP Ltda.",
        display_name="Clínica HTTP",
        registration_identifier="",
        administrative_email="admin@clinic.example",
        administrative_phone="",
        address_line_1="Rua Segura, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("clinic_setup"),
        {
            "stage": "operations",
            "timezone_name": "America/Sao_Paulo",
            "language_code": "pt-BR",
            "service_channels": ["in_person", "video"],
            "monday_start": "08:00",
            "monday_end": "18:00",
            "tuesday_start": "08:00",
            "tuesday_end": "18:00",
            "wednesday_start": "08:00",
            "wednesday_end": "18:00",
            "thursday_start": "08:00",
            "thursday_end": "18:00",
            "friday_start": "08:00",
            "friday_end": "17:00",
            "saturday_start": "",
            "saturday_end": "",
            "sunday_start": "",
            "sunday_end": "",
            "out_of_hours_instructions": "Procure os canais públicos locais.",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('clinic_setup')}?stage=branding"
    configuration = clinic_models.ClinicConfiguration.objects.for_clinic(
        clinic.pk
    ).get()
    assert configuration.service_channels == ["in_person", "video"]
    assert configuration.weekly_hours["monday"] == [{"start": "08:00", "end": "18:00"}]


@pytest.mark.django_db
@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_branding_stage_uploads_logo_and_advances(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica HTTP Ltda.",
        display_name="Clínica HTTP",
        registration_identifier="",
        administrative_email="admin@clinic.example",
        administrative_phone="",
        address_line_1="Rua Segura, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    _complete_operations(clinic, administrator)
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("clinic_setup"),
        {
            "stage": "branding",
            "primary_color": "#1D4ED8",
            "secondary_color": "#93C5FD",
            "logo": SimpleUploadedFile(
                "logo.png",
                b"\x89PNG\r\n\x1a\n" + b"safe-raster-content",
                content_type="image/png",
            ),
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('clinic_setup')}?stage=modules"
    configuration = clinic_models.ClinicConfiguration.objects.for_clinic(
        clinic.pk
    ).get()
    assert configuration.logo.name
    assert configuration.primary_color == "#1D4ED8"
    preview = client.get(f"{reverse('clinic_setup')}?stage=branding")
    preview_content = preview.content.decode()
    assert "Pré-visualização da marca" in preview_content
    assert "--clinic-primary: #1D4ED8" in preview_content
    assert configuration.logo.url in preview_content


@pytest.mark.django_db
@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_modules_stage_enforces_prerequisites_and_advances(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica HTTP Ltda.",
        display_name="Clínica HTTP",
        registration_identifier="",
        administrative_email="admin@clinic.example",
        administrative_phone="",
        address_line_1="Rua Segura, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    _complete_operations(clinic, administrator)
    _complete_branding(clinic, administrator)
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    invalid = client.post(
        reverse("clinic_setup"),
        {"stage": "modules", "enabled_modules": ["agenda"]},
    )
    assert invalid.status_code == 200
    assert "Ative os pré-requisitos" in invalid.content.decode()

    response = client.post(
        reverse("clinic_setup"),
        {
            "stage": "modules",
            "enabled_modules": ["patient_management", "agenda"],
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == f"{reverse('clinic_setup')}?stage=review"
    configuration = clinic_models.ClinicConfiguration.objects.for_clinic(
        clinic.pk
    ).get()
    assert configuration.enabled_modules == ["agenda", "patient_management"]
    assert configuration.modules_updated_by_id == administrator.pk


@pytest.mark.django_db
def test_setup_validation_has_accessible_error_summary(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("clinic_setup"),
        {"stage": "identity", "display_name": "Clínica incompleta"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert 'role="alert"' in content
    assert "data-focus-error-summary" in content
    assert 'href="#id_legal_name"' in content


@pytest.mark.django_db
@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/false",))
def test_branding_rejects_logo_when_malware_scan_does_not_clear() -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Segura Ltda.",
        display_name="Clínica Segura",
        registration_identifier="",
        administrative_email="admin@clinic.example",
        administrative_phone="",
        address_line_1="Rua Segura, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )

    with pytest.raises(ValidationError, match="varredura de segurança"):
        clinic_services.update_clinic_branding(
            clinic_id=clinic.pk,
            actor=administrator,
            logo=SimpleUploadedFile(
                "logo.png",
                b"\x89PNG\r\n\x1a\n" + b"unsafe-content",
                content_type="image/png",
            ),
            primary_color="#1D4ED8",
            secondary_color="#93C5FD",
            request_id=uuid4(),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        ClinicMembership.Role.THERAPIST,
        ClinicMembership.Role.ADMINISTRATIVE_STAFF,
        ClinicMembership.Role.PATIENT,
    ],
)
def test_non_admin_roles_cannot_open_clinic_setup(client: Client, role: str) -> None:
    clinic = ClinicFactory.create()
    actor = UserFactory.create()
    ClinicMembershipFactory.create(clinic=clinic, user=actor, role=role)
    client.force_login(actor)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("clinic_setup"))

    assert response.status_code == 403
    assert not clinic_models.ClinicConfiguration.infrastructure_objects.filter(
        clinic_id=clinic.pk
    ).exists()


@pytest.mark.django_db
@override_settings(PRIVATE_UPLOAD_MALWARE_SCAN_COMMAND=("/bin/true",))
def test_saved_branding_is_applied_to_the_active_tenant_workspace(
    client: Client,
) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Marca Ltda.",
        display_name="Clínica Marca",
        registration_identifier="",
        administrative_email="marca@clinic.example",
        administrative_phone="",
        address_line_1="Rua da Marca, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    configuration = clinic_services.update_clinic_branding(
        clinic_id=clinic.pk,
        actor=administrator,
        logo=SimpleUploadedFile(
            "logo.png",
            b"\x89PNG\r\n\x1a\n" + b"safe-raster-content",
            content_type="image/png",
        ),
        primary_color="#1D4ED8",
        secondary_color="#93C5FD",
        request_id=uuid4(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("workspace_vertical"))

    content = response.content.decode()
    assert "--clinic-primary: #1D4ED8" in content
    assert "--clinic-secondary: #93C5FD" in content
    assert configuration.logo.url in content
    assert 'alt="Clínica Marca"' in content


@pytest.mark.django_db
def test_branding_preview_updates_from_unsaved_form_values(client: Client) -> None:
    clinic = ClinicFactory.create()
    administrator = UserFactory.create()
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=administrator,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    clinic_services.update_clinic_identity(
        clinic_id=clinic.pk,
        actor=administrator,
        legal_name="Clínica Preview Ltda.",
        display_name="Clínica Preview",
        registration_identifier="",
        administrative_email="preview@clinic.example",
        administrative_phone="",
        address_line_1="Rua Preview, 10",
        address_line_2="",
        city="São Paulo",
        region="SP",
        postal_code="01000-000",
        country_code="BR",
        request_id=uuid4(),
    )
    clinic_services.update_clinic_operations(
        clinic_id=clinic.pk,
        actor=administrator,
        timezone_name="America/Sao_Paulo",
        language_code="pt-BR",
        service_channels=["in_person"],
        weekly_hours={day: [] for day, _label in clinic_forms.WEEKDAYS},
        out_of_hours_instructions="",
        request_id=uuid4(),
    )
    client.force_login(administrator)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("clinic_setup") + "?stage=branding")

    content = response.content.decode()
    assert "data-brand-primary-input" in content
    assert "data-brand-secondary-input" in content
    assert "data-brand-logo-input" in content
    assert "data-brand-preview-logo" in content
