"""Tests for clinical episodes and record entries with imutability (PRD 8.18.1)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from medical_records.contracts import (
    AddendumReason,
    EpisodeStatus,
    RecordEntryStatus,
    RecordEntryType,
)
from medical_records.entry_models import (
    RecordEntryVersion,
)
from medical_records.services import (
    create_clinical_episode,
    create_record_addendum,
    create_record_entry_draft,
    sign_record_entry,
    update_record_entry_draft,
)
from people.models import PatientProfile
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Prontuário")


@pytest.fixture
def therapist_user(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_pront@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def other_therapist(clinic: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta2_pront@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def patient_profile(db: Any, clinic: Clinic, therapist_user: Any) -> PatientProfile:
    return PatientProfile.infrastructure_objects.create(
        clinic=clinic,
        user=therapist_user,
        full_name="Paciente Prontuário",
        birth_date="2000-01-15",
    )


def test_create_clinical_episode(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    episode = create_clinical_episode(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        professional_user=therapist_user,
        title="Acompanhamento Terapêutico 2026",
        summary="Sessões semanais.",
    )
    assert episode.status == EpisodeStatus.ACTIVE.value
    assert episode.clinic_id == clinic.id
    assert episode.patient_id == patient_profile.id
    assert episode.title == "Acompanhamento Terapêutico 2026"


def test_create_record_entry_draft_and_version_snapshot(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Evolução da sessão 01",
        content="Paciente relatou melhora no humor.",
        entry_type=RecordEntryType.CLINICAL_EVOLUTION.value,
    )
    assert entry.status == RecordEntryStatus.DRAFT.value
    assert entry.current_version == 1
    assert entry.lock_version == 1
    assert entry.content_hash != ""

    # Version snapshot created automatically
    versions = list(RecordEntryVersion.infrastructure_objects.filter(entry=entry))
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert versions[0].title == "Evolução da sessão 01"


def test_update_draft_with_optimistic_concurrency_control(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Evolução da sessão 02",
        content="Paciente em estado estável.",
    )
    updated = update_record_entry_draft(
        entry=entry,
        editor_user=therapist_user,
        content="Paciente demonstra resistência ao processo.",
        reason_for_change="Correção de registro",
        expected_lock_version=1,
    )
    assert updated.current_version == 2
    assert updated.lock_version == 2
    assert "resistência" in updated.content

    # Two snapshots now
    versions = list(
        RecordEntryVersion.infrastructure_objects.filter(entry=entry).order_by(
            "version_number"
        )
    )
    assert len(versions) == 2
    assert versions[1].reason_for_change == "Correção de registro"


def test_optimistic_lock_conflict_raises(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Evolução da sessão 03",
        content="Conteúdo original.",
    )
    # First update: OK (expects lock_version=1)
    update_record_entry_draft(
        entry=entry,
        editor_user=therapist_user,
        content="Primeira edição.",
        expected_lock_version=1,
    )
    # Second attempt with stale lock_version=1 should fail
    with pytest.raises(ValueError, match="Optimistic lock conflict"):
        update_record_entry_draft(
            entry=entry,
            editor_user=therapist_user,
            content="Edição conflitante.",
            expected_lock_version=1,
        )


def test_signed_entry_becomes_immutable(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Evolução assinada",
        content="Conteúdo final da sessão.",
    )
    signed = sign_record_entry(entry=entry, signing_user=therapist_user)
    assert signed.status == RecordEntryStatus.SIGNED.value
    assert signed.signed_at is not None
    assert signed.signed_by_id == therapist_user.pk

    # Attempt to edit a signed entry must fail
    with pytest.raises(PermissionError):
        update_record_entry_draft(
            entry=signed,
            editor_user=therapist_user,
            content="Tentativa de alteração pós-assinatura.",
            expected_lock_version=signed.lock_version,
        )


def test_addendum_on_signed_entry(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Evolução com adendo",
        content="Conteúdo clínico inicial.",
    )
    sign_record_entry(entry=entry, signing_user=therapist_user)

    addendum = create_record_addendum(
        entry=entry,
        author_user=therapist_user,
        content="Informação complementar adicionada após assinatura.",
        reason=AddendumReason.LATE_ENTRY.value,
    )
    assert addendum.addendum_number == 1
    assert addendum.is_signed is True
    assert addendum.content_hash != ""

    # Entry status updated to AMENDED
    entry.refresh_from_db()
    assert entry.status == RecordEntryStatus.AMENDED.value

    # Second addendum gets incremented number
    addendum2 = create_record_addendum(
        entry=entry,
        author_user=therapist_user,
        content="Segunda informação complementar.",
        reason=AddendumReason.SUPPLEMENTAL_INFO.value,
    )
    assert addendum2.addendum_number == 2


def test_addendum_cannot_be_created_on_draft(
    clinic: Clinic, therapist_user: Any, patient_profile: PatientProfile
) -> None:
    entry = create_record_entry_draft(
        clinic_id=clinic.id,
        patient_id=patient_profile.id,
        author_user=therapist_user,
        title="Rascunho",
        content="Ainda em rascunho.",
    )
    with pytest.raises(PermissionError):
        create_record_addendum(
            entry=entry,
            author_user=therapist_user,
            content="Tentativa de adendo em rascunho.",
        )
