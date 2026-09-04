"""Tests for optional spirituality and history purge (8.16.4)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from people.models import PatientProfile
from support_network.contracts import (
    ContemplativeCategory,
    SpiritualityTradition,
)
from support_network.models import ContemplativeHistory
from support_network.selectors import contemplative_catalog_for_patient
from support_network.spirituality_services import (
    configure_spirituality_preference,
    log_contemplative_session,
    publish_contemplative_content,
    purge_contemplative_history,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Bem-estar")


@pytest.fixture
def patient_profile(db: Any, clinic_fixture: Clinic) -> PatientProfile:
    user = UserFactory.create(email="paciente_contemplativo@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic_fixture,
        user=user,
        full_name="Paciente Contemplativo",
        birth_date="1992-07-20",
    )


@pytest.fixture
def vetted_contents(db: Any) -> list[Any]:
    secular = publish_contemplative_content(
        title="Pausa para Respiração Consciente",
        description="Exercício secular focado na atenção plena da respiração.",
        content_text="Sente-se confortavelmente, observe o ar entrando e saindo...",
        category=ContemplativeCategory.BREATH_AWARENESS.value,
        tradition=SpiritualityTradition.SECULAR.value,
        duration_minutes=3,
        is_secular_equivalent=True,
        author_attribution="Equipe de Mindfulness",
    )
    buddhist = publish_contemplative_content(
        title="Meditação Metta (Bondade Amorosa)",
        description="Prática tradicional budista de votos de paz para si e outros.",
        content_text=(
            "Que eu esteja seguro, que todos os seres estejam livres de sofrimento..."
        ),
        category=ContemplativeCategory.LOVING_KINDNESS.value,
        tradition=SpiritualityTradition.BUDDHIST.value,
        duration_minutes=10,
        is_secular_equivalent=True,
        author_attribution="Tradição Theravada",
    )
    christian = publish_contemplative_content(
        title="Oração Centrante",
        description="Prática contemplativa cristã de silêncio e acolhimento.",
        content_text="Escolha uma palavra sagrada como símbolo da sua intenção...",
        category=ContemplativeCategory.VALUES_REFLECTION.value,
        tradition=SpiritualityTradition.CHRISTIAN.value,
        duration_minutes=10,
        is_secular_equivalent=True,
        author_attribution="Contemplative Outreach",
    )
    return [secular, buddhist, christian]


@pytest.mark.django_db
def test_disabled_by_default_returns_empty_catalog(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    vetted_contents: list[Any],
) -> None:
    """Without explicit opt-in, non-adherents receive zero content."""
    catalog = contemplative_catalog_for_patient(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    assert catalog == []


@pytest.mark.django_db
def test_explicit_opt_in_secular_preference(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    vetted_contents: list[Any],
) -> None:
    pref = configure_spirituality_preference(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        is_enabled=True,
        tradition=SpiritualityTradition.SECULAR.value,
        secular_alternative_enabled=True,
        disclaimer_acknowledged=True,
    )
    assert pref.is_enabled is True
    assert pref.tradition == "secular"
    assert pref.opt_in_date is not None

    catalog = contemplative_catalog_for_patient(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    # Only secular content is shown
    assert len(catalog) == 1
    assert catalog[0].tradition == "secular"


@pytest.mark.django_db
def test_tradition_opt_in_includes_secular_alternative(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    vetted_contents: list[Any],
) -> None:
    configure_spirituality_preference(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        is_enabled=True,
        tradition=SpiritualityTradition.BUDDHIST.value,
        secular_alternative_enabled=True,
    )

    catalog = contemplative_catalog_for_patient(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    # Includes buddhist and secular alternative
    traditions = {c.tradition for c in catalog}
    assert traditions == {"buddhist", "secular"}


@pytest.mark.django_db
def test_logging_and_immediate_history_purge(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    vetted_contents: list[Any],
) -> None:
    """PRD requirement: Right to be forgotten, immediate unrecoverable history purge."""
    configure_spirituality_preference(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        is_enabled=True,
    )

    content = vetted_contents[0]
    log1 = log_contemplative_session(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        content_id=content.id,
        duration_spent_seconds=180,
        completed=True,
    )
    assert log1.id is not None
    assert ContemplativeHistory.objects.for_clinic(clinic_fixture.id).count() == 1

    # Immediate purge
    deleted_count = purge_contemplative_history(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    assert deleted_count == 1
    assert ContemplativeHistory.objects.for_clinic(clinic_fixture.id).count() == 0


@pytest.mark.django_db
def test_disabling_spirituality_automatically_purges_history(
    clinic_fixture: Clinic,
    patient_profile: PatientProfile,
    vetted_contents: list[Any],
) -> None:
    # Enable
    configure_spirituality_preference(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        is_enabled=True,
    )
    log_contemplative_session(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        content_id=vetted_contents[0].id,
        duration_spent_seconds=200,
    )
    assert ContemplativeHistory.objects.for_clinic(clinic_fixture.id).count() == 1

    # Disable opt-in
    configure_spirituality_preference(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
        is_enabled=False,
    )
    # History must be automatically wiped clean
    assert ContemplativeHistory.objects.for_clinic(clinic_fixture.id).count() == 0
    catalog = contemplative_catalog_for_patient(
        clinic_id=clinic_fixture.id,
        patient_profile_id=patient_profile.id,
    )
    assert catalog == []
