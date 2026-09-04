"""Tests for rollout flags, kill switch, and operational metrics (PRD 8.17.5)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from communities.contracts import GroupVisibility
from communities.interaction_services import publish_post
from communities.rollout_services import (
    record_daily_community_metric,
    set_community_rollout_flags,
    trigger_emergency_kill_switch,
)
from communities.selectors import get_community_rollout_status
from communities.services import (
    create_community_group,
    join_community_group,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Governança")


@pytest.fixture
def therapist_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="terapeuta_gov@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def member_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="membro_gov@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


def test_rollout_flag_configuration(
    clinic_fixture: Clinic,
) -> None:
    flag = set_community_rollout_flags(
        clinic_id=clinic_fixture.id,
        communities_enabled=True,
        gamification_enabled=True,
        allowed_age_tiers=["ADULT", "MINOR_OLDER"],
        slow_mode_enforced=True,
    )

    assert flag.communities_enabled is True
    assert flag.gamification_enabled is True
    assert "MINOR_OLDER" in flag.allowed_age_tiers

    fetched = get_community_rollout_status(clinic_id=clinic_fixture.id)
    assert fetched.communities_enabled is True


def test_emergency_moderation_kill_switch_blocks_posting(
    clinic_fixture: Clinic,
    therapist_user: Any,
    member_user: Any,
) -> None:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=therapist_user,
        name="Grupo Teste Trava de Emergência",
        slug="trava-emergencia",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
    )
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        user=member_user,
    )

    # Initial post works fine
    publish_post(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        author_user=member_user,
        content="Postagem inicial permitida.",
    )

    # Activate emergency kill switch due to moderation queue overload
    trigger_emergency_kill_switch(
        clinic_id=clinic_fixture.id,
        activate=True,
        reason="Fila de moderação atingiu nível crítico.",
    )

    # Subsequent post attempt must be blocked
    with pytest.raises(PermissionError, match="User is not authorized to post"):
        publish_post(
            clinic_id=clinic_fixture.id,
            group_id=group.id,
            author_user=member_user,
            content="Tentativa de envio com trava ativada.",
        )


def test_aggregate_daily_metric_logging(
    clinic_fixture: Clinic,
) -> None:
    metric = record_daily_community_metric(
        clinic_id=clinic_fixture.id,
        posts_delta=15,
        comments_delta=42,
        reports_delta=3,
        moderation_actions_delta=2,
        appeals_delta=1,
        appeals_upheld_delta=1,
        sla_minutes=35.5,
    )

    assert metric.posts_created == 15
    assert metric.comments_created == 42
    assert metric.reports_submitted == 3
    assert metric.moderation_actions_taken == 2
    assert metric.appeals_upheld == 1
    assert metric.average_sla_resolution_minutes == 35.5
