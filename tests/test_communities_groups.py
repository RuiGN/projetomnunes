"""Tests for community groups, memberships, and invitations (PRD 8.17.1)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from communities.contracts import (
    GroupType,
    GroupVisibility,
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
)
from communities.selectors import (
    get_community_directory_for_user,
    get_user_joined_groups,
)
from communities.services import (
    close_community_group,
    create_community_group,
    invite_user_to_group,
    join_community_group,
    leave_community_group,
    respond_to_group_invitation,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Social 1")


@pytest.fixture
def other_clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Social 2")


@pytest.fixture
def member_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="membro@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def other_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="outro@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def therapist_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


def test_create_community_group_registers_creator_as_owner(
    clinic_fixture: Clinic, therapist_user: Any
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Ansiedade e Respiração",
        slug="ansiedade-respiracao",
        description="Espaço de apoio mútuo para controle de ansiedade.",
        group_type=GroupType.THEMATIC_APPROVED.value,
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
        allowed_age_tiers=["ADULT"],
    )

    assert group.is_active is True
    assert group.clinic_id == clinic_fixture.id

    joined = get_user_joined_groups(
        clinic_id=clinic_fixture.id,
        user=therapist_user,
    )
    assert len(joined) == 1
    assert joined[0].id == group.id


def test_multi_tenant_isolation_hides_groups_between_clinics(
    clinic_fixture: Clinic,
    other_clinic_fixture: Clinic,
    therapist_user: Any,
    other_user: Any,
) -> None:
    group_c1 = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Exclusivo C1",
        slug="grupo-c1",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
    )

    directory_c1 = get_community_directory_for_user(
        clinic_id=clinic_fixture.id,
        user=other_user,
    )
    directory_c2 = get_community_directory_for_user(
        clinic_id=other_clinic_fixture.id,
        user=other_user,
    )

    assert any(g.id == group_c1.id for g in directory_c1)
    assert not any(g.id == group_c1.id for g in directory_c2)


def test_community_directory_filters_by_age_tier(
    clinic_fixture: Clinic, therapist_user: Any, member_user: Any
) -> None:
    adult_group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Adultos",
        slug="grupo-adultos",
        allowed_age_tiers=["ADULT"],
    )
    minor_group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Adolescentes Protegido",
        slug="grupo-adolescentes",
        allowed_age_tiers=["MINOR_OLDER"],
    )

    adult_view = get_community_directory_for_user(
        clinic_id=clinic_fixture.id,
        user=member_user,
        user_age_tier="ADULT",
    )
    minor_view = get_community_directory_for_user(
        clinic_id=clinic_fixture.id,
        user=member_user,
        user_age_tier="MINOR_OLDER",
    )

    assert any(g.id == adult_group.id for g in adult_view)
    assert not any(g.id == minor_group.id for g in adult_view)

    assert any(g.id == minor_group.id for g in minor_view)
    assert not any(g.id == adult_group.id for g in minor_view)


def test_invitation_accept_flow_with_pseudonym(
    clinic_fixture: Clinic,
    therapist_user: Any,
    member_user: Any,
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Fechado de Sobriedade",
        slug="sobriedade-apoio",
        group_type=GroupType.PRIVATE_INVITE_ONLY.value,
        visibility=GroupVisibility.PRIVATE.value,
    )

    invitation = invite_user_to_group(
        clinic_id=clinic_fixture.id,
        inviter_user=therapist_user,
        group_id=group.id,
        invitee_email="membro@exemplo.com",
        role_offered=MembershipRole.MEMBER.value,
    )
    assert invitation.status == InvitationStatus.PENDING.value

    membership = respond_to_group_invitation(
        clinic_id=clinic_fixture.id,
        invitation_id=invitation.id,
        user=member_user,
        accept=True,
        pseudonym="CaminhanteSereno",
    )

    assert membership is not None
    assert membership.status == MembershipStatus.ACTIVE.value
    assert membership.display_name == "CaminhanteSereno"


def test_invitation_decline_flow(
    clinic_fixture: Clinic,
    therapist_user: Any,
    member_user: Any,
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Convidativo",
        slug="grupo-convidativo",
    )

    invitation = invite_user_to_group(
        clinic_id=clinic_fixture.id,
        inviter_user=therapist_user,
        group_id=group.id,
        invitee_email="membro@exemplo.com",
    )

    membership = respond_to_group_invitation(
        clinic_id=clinic_fixture.id,
        invitation_id=invitation.id,
        user=member_user,
        accept=False,
    )
    assert membership is None

    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.DECLINED.value


def test_immediate_exit_from_group(
    clinic_fixture: Clinic,
    therapist_user: Any,
    member_user: Any,
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Aberto para Saída Imediata",
        slug="saida-imediata-grupo",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
    )

    membership = join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        user=member_user,
    )
    assert membership.status == MembershipStatus.ACTIVE.value

    leave_community_group(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        user=member_user,
    )

    joined = get_user_joined_groups(
        clinic_id=clinic_fixture.id,
        user=member_user,
    )
    assert not any(g.id == group.id for g in joined)


def test_close_community_group_soft_delete(
    clinic_fixture: Clinic,
    therapist_user: Any,
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo a Encerrar",
        slug="grupo-encerrar",
    )

    closed = close_community_group(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        closed_by=therapist_user,
    )

    assert closed.is_active is False
    assert closed.closed_at is not None
    assert closed.closed_by == therapist_user
