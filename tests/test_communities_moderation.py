"""Tests for moderation, evidence vault, audit trails, and appeals (PRD 8.17.3)."""

from typing import Any

import pytest

from clinics.models import Clinic, ClinicMembership
from communities.contracts import (
    AppealStatus,
    ContentStatus,
    GroupVisibility,
    ModerationDecision,
    ModerationSeverity,
    ModerationStatus,
    ViolationCategory,
)
from communities.interaction_services import publish_post
from communities.moderation_models import ModerationAuditTrail
from communities.moderation_services import (
    apply_moderation_decision,
    file_moderation_appeal,
    report_content,
    resolve_moderation_appeal,
)
from communities.selectors import get_case_evidence, get_moderation_queue
from communities.services import (
    create_community_group,
    join_community_group,
)
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


@pytest.fixture
def clinic_fixture(db: Any) -> Clinic:
    return ClinicFactory.create(name="Clínica Moderação")


@pytest.fixture
def moderator_one(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="mod1@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.CLINIC_ADMIN,
        is_active=True,
    )
    return user


@pytest.fixture
def moderator_two(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="mod2@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.THERAPIST,
        is_active=True,
    )
    return user


@pytest.fixture
def reporter_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="denunciante@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def reported_user(clinic_fixture: Clinic) -> Any:
    user = UserFactory.create(email="denunciado@exemplo.com")
    ClinicMembershipFactory.create(
        clinic=clinic_fixture,
        user=user,
        role=ClinicMembership.Role.PATIENT,
        is_active=True,
    )
    return user


@pytest.fixture
def test_post(
    clinic_fixture: Clinic, moderator_one: Any, reported_user: Any
) -> Any:
    group = create_community_group(
        clinic_id=clinic_fixture.id,
        creator_user=moderator_one,
        name="Grupo Teste Moderação",
        slug="mod-teste",
        visibility=GroupVisibility.TENANT_DIRECTORY.value,
    )
    join_community_group(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        user=reported_user,
    )
    return publish_post(
        clinic_id=clinic_fixture.id,
        group_id=group.id,
        author_user=reported_user,
        content="Mensagem hostil e agressiva violando as diretrizes.",
    )


def test_report_content_creates_case_and_segregated_evidence_vault(
    clinic_fixture: Clinic,
    reporter_user: Any,
    reported_user: Any,
    test_post: Any,
    moderator_one: Any,
) -> None:
    case = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.HARASSMENT.value,
        severity=ModerationSeverity.MEDIUM.value,
    )

    assert case.status == ModerationStatus.PENDING_TRIAGE.value
    assert case.reported_user_id == reported_user.pk
    # Reporter is registered in case for audit
    assert case.reporter_id == reporter_user.pk

    # Evidence vault snapshot was saved
    evidence = get_case_evidence(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        moderator_user=moderator_one,
    )
    assert (
        evidence.content_snapshot
        == "Mensagem hostil e agressiva violando as diretrizes."
    )
    assert evidence.author_id == reported_user.pk

    # Audit trail started
    audit_count = ModerationAuditTrail.objects.for_clinic(clinic_fixture.id).filter(
        case=case
    ).count()
    assert audit_count >= 1


def test_priority_score_and_queue_sorting(
    clinic_fixture: Clinic,
    reporter_user: Any,
    test_post: Any,
    moderator_one: Any,
) -> None:
    # Low severity case
    case_low = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.SPAM.value,
        severity=ModerationSeverity.LOW.value,
    )

    # Critical severity case
    case_crit = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.HATE_SPEECH.value,
        severity=ModerationSeverity.CRITICAL.value,
    )

    assert case_crit.priority_score > case_low.priority_score
    assert case_crit.requires_double_review is True
    assert case_low.requires_double_review is False

    queue = get_moderation_queue(
        clinic_id=clinic_fixture.id,
        moderator_user=moderator_one,
    )
    # The higher priority case must be first
    assert queue[0].id == case_crit.id


def test_human_decision_mandatory_enforces_sanction(
    clinic_fixture: Clinic,
    reporter_user: Any,
    test_post: Any,
    moderator_one: Any,
) -> None:
    case = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.OTHER.value,
        severity=ModerationSeverity.MEDIUM.value,
    )

    # Reject empty justification
    with pytest.raises(ValueError, match="Human justification is mandatory"):
        apply_moderation_decision(
            clinic_id=clinic_fixture.id,
            case_id=case.id,
            moderator_user=moderator_one,
            decision=ModerationDecision.CONTENT_REMOVED.value,
            justification="   ",
        )

    # Apply valid human decision
    updated_case = apply_moderation_decision(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        moderator_user=moderator_one,
        decision=ModerationDecision.CONTENT_REMOVED.value,
        justification="Conteúdo ofensivo incompatível com as regras de convivência.",
    )

    assert updated_case.status == ModerationStatus.ACTIONED.value

    test_post.refresh_from_db()
    assert test_post.status == ContentStatus.HIDDEN_BY_MODERATOR.value


def test_double_review_workflow_for_critical_cases(
    clinic_fixture: Clinic,
    reporter_user: Any,
    test_post: Any,
    moderator_one: Any,
    moderator_two: Any,
) -> None:
    case = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.UNSAFE_CONTENT.value,
        severity=ModerationSeverity.HIGH.value,
    )
    assert case.requires_double_review is True

    # First reviewer records initial stance
    case_step1 = apply_moderation_decision(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        moderator_user=moderator_one,
        decision=ModerationDecision.USER_SUSPENDED.value,
        justification="Violação grave com risco à integridade.",
        is_second_review=False,
    )
    assert case_step1.status == ModerationStatus.IN_REVIEW.value

    # First reviewer cannot self-concur as second reviewer
    with pytest.raises(ValueError, match="Second reviewer must be distinct"):
        apply_moderation_decision(
            clinic_id=clinic_fixture.id,
            case_id=case.id,
            moderator_user=moderator_one,
            decision=ModerationDecision.USER_SUSPENDED.value,
            justification="Tentativa de auto-aprovação.",
            is_second_review=True,
        )

    # Second independent reviewer completes the sanction
    final_case = apply_moderation_decision(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        moderator_user=moderator_two,
        decision=ModerationDecision.USER_SUSPENDED.value,
        justification="Concordo plenamente com a suspensão preventiva.",
        is_second_review=True,
    )
    assert final_case.status == ModerationStatus.ACTIONED.value


def test_appeal_and_restoration_workflow(
    clinic_fixture: Clinic,
    reporter_user: Any,
    reported_user: Any,
    test_post: Any,
    moderator_one: Any,
    moderator_two: Any,
) -> None:
    # 1. Open case and action content removal
    case = report_content(
        clinic_id=clinic_fixture.id,
        reporter_user=reporter_user,
        target_type="post",
        target_id=test_post.id,
        violation_category=ViolationCategory.OTHER.value,
        severity=ModerationSeverity.MEDIUM.value,
    )
    apply_moderation_decision(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        moderator_user=moderator_one,
        decision=ModerationDecision.CONTENT_REMOVED.value,
        justification="Remoção provisória de postagem contestada.",
    )

    test_post.refresh_from_db()
    assert test_post.status == ContentStatus.HIDDEN_BY_MODERATOR.value

    # 2. Sanctioned user files appeal
    appeal = file_moderation_appeal(
        clinic_id=clinic_fixture.id,
        case_id=case.id,
        appellant_user=reported_user,
        appeal_grounds=(
            "Houve mal-entendido; a citação era parte de um poema literário."
        ),
    )
    assert appeal.status == AppealStatus.PENDING.value

    # 3. Independent moderator upholds the appeal and restores the post
    resolved_appeal = resolve_moderation_appeal(
        clinic_id=clinic_fixture.id,
        appeal_id=appeal.id,
        reviewer_user=moderator_two,
        accept_appeal=True,
        reviewer_notes="Recurso procedente. O texto tem caráter puramente artístico.",
    )
    assert resolved_appeal.status == AppealStatus.ACCEPTED.value

    test_post.refresh_from_db()
    # Content restored back to published!
    assert test_post.status == ContentStatus.PUBLISHED.value
