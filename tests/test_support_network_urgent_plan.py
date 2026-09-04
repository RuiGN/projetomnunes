"""Tests for urgent support plan, contacts, preview, and resources (8.16.3)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from support_network.models import (
    MANDATORY_URGENT_DISCLAIMER,
    UrgentActionLog,
    UrgentLocalResource,
)
from support_network.selectors import urgent_support_plan_for_patient
from support_network.urgent_services import (
    confirm_urgent_contact_action,
    create_or_update_urgent_plan,
    prepare_urgent_action_preview,
    register_urgent_contact,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Urgência")


@pytest.fixture
def other_clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Outra Clínica Urgência")


@pytest.fixture
def patient_profile(db: Any, clinic_fixture: Clinic) -> PatientProfile:
    user = UserFactory.create(email="paciente_urgente@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic_fixture,
        user=user,
        full_name="Paciente Urgente",
        birth_date="1988-03-12",
    )


@pytest.mark.django_db
def test_create_urgent_support_plan_and_ordered_contacts(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
) -> None:
    plan = create_or_update_urgent_plan(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        personal_instructions="Lembrar de respirar devagar e beber água fria.",
        calming_strategies=["Respiração quadrada 4-4-4-4", "Ouvir música suave"],
        preferred_language="pt-BR",
        region="BR-SP",
    )

    assert plan.patient_id == patient_profile.id
    assert plan.disclaimer_acknowledged is True
    assert len(plan.calming_strategies) == 2

    # Register contacts with priority order
    c1 = register_urgent_contact(
        clinic_id=clinic_fixture.id,
        plan_id=plan.id,
        priority_order=1,
        name="Irmã Joana",
        relationship="Irmã",
        phone_number="+5511988887777",
    )
    c2 = register_urgent_contact(
        clinic_id=clinic_fixture.id,
        plan_id=plan.id,
        priority_order=2,
        name="Amigo Pedro",
        relationship="Amigo",
        phone_number="+5511977776666",
    )

    contacts = list(plan.contacts.all().order_by("priority_order"))
    assert len(contacts) == 2
    assert contacts[0].id == c1.id
    assert contacts[1].id == c2.id


@pytest.mark.django_db
def test_prepare_urgent_action_preview_and_explicit_confirmation(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
) -> None:
    plan = create_or_update_urgent_plan(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        personal_instructions="Instruções pessoais",
    )
    contact = register_urgent_contact(
        clinic_id=clinic_fixture.id,
        plan_id=plan.id,
        name="Contato Confiança",
        relationship="Amigo",
        phone_number="+5511988889999",
        message_template="Preciso de ajuda no momento.",
    )

    # Preview generation
    preview = prepare_urgent_action_preview(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        contact_id=contact.id,
    )
    assert preview.contact_id == contact.id
    assert preview.contact_phone == "+5511988889999"
    assert preview.requires_explicit_confirmation is True
    assert preview.disclaimer == MANDATORY_URGENT_DISCLAIMER

    # Preview logged but NOT confirmed
    preview_log = UrgentActionLog.objects.for_clinic(clinic_fixture.id).last()
    assert preview_log is not None
    assert preview_log.confirmed_explicitly is False
    assert preview_log.action_type == "PREVIEW_GENERATED"

    # Refuse without confirmation -> Error
    with pytest.raises(ValueError, match="exige confirmação explícita"):
        confirm_urgent_contact_action(
            clinic_id=clinic_fixture.id,
            patient_profile_id=patient_profile.id,
            contact_id=contact.id,
            confirmed_by_user=False,
        )

    # Explicit confirmation
    confirmed_log = confirm_urgent_contact_action(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        contact_id=contact.id,
        confirmed_by_user=True,
    )
    assert confirmed_log.confirmed_explicitly is True
    assert confirmed_log.action_type == "CONFIRMED_BY_USER"
    assert confirmed_log.disclaimer_shown is True


@pytest.mark.django_db
def test_selector_returns_plan_contacts_and_local_resources(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
) -> None:
    # Seed public emergency resource
    UrgentLocalResource.infrastructure_objects.create(
        region="BR",
        resource_name="CVV - Centro de Valorização da Vida",
        service_type="CRISIS_HOTLINE",
        contact_number="188",
        hours_of_operation="24 horas",
        is_active=True,
    )
    UrgentLocalResource.infrastructure_objects.create(
        region="BR",
        resource_name="SAMU",
        service_type="MEDICAL_EMERGENCY",
        contact_number="192",
        hours_of_operation="24 horas",
        is_active=True,
    )

    create_or_update_urgent_plan(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        region="BR",
    )

    overview = urgent_support_plan_for_patient(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )

    assert overview["plan"] is not None
    assert len(overview["local_resources"]) >= 2
    resource_names = [r.resource_name for r in overview["local_resources"]]
    assert "CVV - Centro de Valorização da Vida" in resource_names
    assert "SAMU" in resource_names


@pytest.mark.django_db
def test_urgent_plan_multi_tenant_isolation(
    clinic_fixture: Clinic,
    other_clinic_fixture: Clinic,
    patient_profile: PatientProfile,
) -> None:
    _ = create_or_update_urgent_plan(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        personal_instructions="Instruções privadas",
    )

    # Other clinic cannot access plan
    overview_other = urgent_support_plan_for_patient(
        clinic_id=other_clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    assert overview_other["plan"] is None
