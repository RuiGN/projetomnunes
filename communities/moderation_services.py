"""Services for moderation, evidence vault, audit trails, and appeals (8.17.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from communities.community_models import (
    CommunityMembership,
)
from communities.contracts import (
    AppealStatus,
    ContentStatus,
    MembershipStatus,
    ModerationDecision,
    ModerationSeverity,
    ModerationStatus,
    ViolationCategory,
)
from communities.events import (
    moderation_actioned,
    moderation_appeal_filed,
    moderation_appeal_resolved,
    moderation_case_opened,
)
from communities.interaction_models import (
    CommunityComment,
    CommunityPost,
)
from communities.moderation_models import (
    EvidenceVault,
    ModerationAppeal,
    ModerationAuditTrail,
    ModerationCase,
)
from communities.policies import can_access_moderation_console


def calculate_triage_priority(
    violation_category: str,
    severity: str,
) -> tuple[int, timedelta, bool]:
    """Derive queue priority score, SLA window, and double-review requirement."""
    score = 50
    sla_delta = timedelta(hours=24)
    requires_double_review = False

    if severity == ModerationSeverity.CRITICAL.value:
        score = 95
        sla_delta = timedelta(hours=4)
        requires_double_review = True
    elif severity == ModerationSeverity.HIGH.value:
        score = 80
        sla_delta = timedelta(hours=12)
        requires_double_review = True
    elif severity == ModerationSeverity.LOW.value:
        score = 25
        sla_delta = timedelta(hours=48)

    if violation_category in {
        ViolationCategory.HATE_SPEECH.value,
        ViolationCategory.UNSAFE_CONTENT.value,
    }:
        score = max(score, 85)

    return score, sla_delta, requires_double_review


@transaction.atomic
def report_content(
    *,
    clinic_id: UUID,
    reporter_user: AbstractBaseUser,
    target_type: str,  # "post" or "comment"
    target_id: UUID,
    violation_category: str = ViolationCategory.OTHER.value,
    severity: str = ModerationSeverity.MEDIUM.value,
) -> ModerationCase:
    """File a report against content with segregated evidence snapshot."""
    reported_user: AbstractBaseUser
    content_snapshot: str

    if target_type == "post":
        post = CommunityPost.objects.for_clinic(clinic_id).get(id=target_id)
        reported_user = post.author
        content_snapshot = post.content
    elif target_type == "comment":
        comment = CommunityComment.objects.for_clinic(clinic_id).get(id=target_id)
        reported_user = comment.author
        content_snapshot = comment.content
    else:
        raise ValueError(f"Unsupported target type for moderation: {target_type}")

    priority_score, sla_delta, requires_double_review = calculate_triage_priority(
        violation_category=violation_category,
        severity=severity,
    )
    sla_deadline = timezone.now() + sla_delta

    case = ModerationCase.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        target_type=target_type,
        target_id=target_id,
        reporter=cast(Any, reporter_user),
        reported_user=cast(Any, reported_user),
        violation_category=violation_category,
        severity=severity,
        priority_score=priority_score,
        status=ModerationStatus.PENDING_TRIAGE.value,
        sla_deadline=sla_deadline,
        requires_double_review=requires_double_review,
    )

    # Segregated snapshot preserved in EvidenceVault
    EvidenceVault.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        content_snapshot=content_snapshot,
        author_id=reported_user.pk,
        metadata_json={
            "target_type": target_type,
            "target_id": str(target_id),
            "violation_category": violation_category,
        },
    )

    # Initial append-only audit trail
    ModerationAuditTrail.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        actor=cast(Any, reporter_user),
        action_name="CASE_OPENED",
        previous_status="NONE",
        new_status=ModerationStatus.PENDING_TRIAGE.value,
        details=f"Report filed for {violation_category} ({severity})",
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=reporter_user.pk,
        action="communities.report_filed",
        resource_type="moderation_case",
        resource_id=str(case.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    moderation_case_opened.send(sender=ModerationCase, case_id=case.id)
    return case


@transaction.atomic
def apply_moderation_decision(
    *,
    clinic_id: UUID,
    case_id: UUID,
    moderator_user: AbstractBaseUser,
    decision: str,
    justification: str,
    is_second_review: bool = False,
) -> ModerationCase:
    """Enforce human moderation decision with mandatory audit trail."""
    if not can_access_moderation_console(user=moderator_user, clinic_id=clinic_id):
        raise PermissionError("User is not authorized to act as a moderator.")

    valid_decisions = {d.value for d in ModerationDecision}
    if decision not in valid_decisions:
        raise ValueError(f"Invalid decision: {decision}")

    if not justification.strip():
        raise ValueError(
            "Human justification is mandatory for any moderation decision."
        )

    case = ModerationCase.objects.for_clinic(clinic_id).get(id=case_id)
    previous_status = case.status

    if case.requires_double_review and not is_second_review:
        # First review of a high/critical case
        case.assigned_moderator = cast(Any, moderator_user)
        case.decision = decision
        case.justification = justification
        case.actioned_at = timezone.now()
        case.status = ModerationStatus.IN_REVIEW.value
        case.save(
            update_fields=[
                "assigned_moderator",
                "decision",
                "justification",
                "actioned_at",
                "status",
                "updated_at",
            ]
        )

        ModerationAuditTrail.objects.for_clinic(clinic_id).create(
            clinic_id=clinic_id,
            case=case,
            actor=cast(Any, moderator_user),
            action_name="FIRST_REVIEW_RECORDED",
            previous_status=previous_status,
            new_status=ModerationStatus.IN_REVIEW.value,
            details=f"Decision: {decision}. Awaiting second independent review.",
        )
        return case

    if is_second_review:
        if case.assigned_moderator_id == moderator_user.pk:
            raise ValueError("Second reviewer must be distinct from first reviewer.")
        case.second_moderator = cast(Any, moderator_user)
        case.second_decision = decision
        case.second_justification = justification
        case.second_actioned_at = timezone.now()
    else:
        case.assigned_moderator = cast(Any, moderator_user)
        case.decision = decision
        case.justification = justification
        case.actioned_at = timezone.now()

    # Finalize decision and execute sanctions
    effective_decision = decision
    if decision == ModerationDecision.NO_ACTION.value:
        case.status = ModerationStatus.DISMISSED.value
    else:
        case.status = ModerationStatus.ACTIONED.value
        _execute_sanction(clinic_id=clinic_id, case=case, decision=effective_decision)

    case.save()

    ModerationAuditTrail.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        actor=cast(Any, moderator_user),
        action_name="DECISION_FINALIZED",
        previous_status=previous_status,
        new_status=case.status,
        details=f"Decision: {effective_decision}. Justification: {justification}",
    )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=moderator_user.pk,
        action="communities.moderation_actioned",
        resource_type="moderation_case",
        resource_id=str(case.id),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    moderation_actioned.send(sender=ModerationCase, case_id=case.id)
    return case


def _execute_sanction(
    *,
    clinic_id: UUID,
    case: ModerationCase,
    decision: str,
) -> None:
    """Internal helper to enact the consequences of a finalized moderation decision."""
    if decision == ModerationDecision.CONTENT_REMOVED.value:
        if case.target_type == "post":
            CommunityPost.objects.for_clinic(clinic_id).filter(id=case.target_id).update(
                status=ContentStatus.HIDDEN_BY_MODERATOR.value
            )
        elif case.target_type == "comment":
            CommunityComment.objects.for_clinic(clinic_id).filter(
                id=case.target_id
            ).update(status=ContentStatus.HIDDEN_BY_MODERATOR.value)
    elif decision == ModerationDecision.USER_SUSPENDED.value:
        CommunityMembership.objects.for_clinic(clinic_id).filter(
            user=case.reported_user
        ).update(status=MembershipStatus.SUSPENDED.value)
    elif decision == ModerationDecision.USER_BANNED.value:
        CommunityMembership.objects.for_clinic(clinic_id).filter(
            user=case.reported_user
        ).update(status=MembershipStatus.REMOVED.value)


@transaction.atomic
def file_moderation_appeal(
    *,
    clinic_id: UUID,
    case_id: UUID,
    appellant_user: AbstractBaseUser,
    appeal_grounds: str,
) -> ModerationAppeal:
    """Submit an appeal against an adverse moderation sanction."""
    case = ModerationCase.objects.for_clinic(clinic_id).get(id=case_id)
    if case.reported_user_id != appellant_user.pk:
        raise PermissionError("Only the sanctioned user may file an appeal.")
    if case.status != ModerationStatus.ACTIONED.value:
        raise ValueError("Can only appeal finalized moderation actions.")

    if not appeal_grounds.strip():
        raise ValueError("Appeal grounds must be provided.")

    appeal = ModerationAppeal.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        appellant=cast(Any, appellant_user),
        appeal_grounds=appeal_grounds,
        status=AppealStatus.PENDING.value,
    )

    case.status = ModerationStatus.APPEALED.value
    case.save(update_fields=["status", "updated_at"])

    ModerationAuditTrail.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        actor=cast(Any, appellant_user),
        action_name="APPEAL_FILED",
        previous_status=ModerationStatus.ACTIONED.value,
        new_status=ModerationStatus.APPEALED.value,
        details=f"Appeal filed: {appeal_grounds[:100]}",
    )

    moderation_appeal_filed.send(sender=ModerationAppeal, appeal_id=appeal.id)
    return appeal


@transaction.atomic
def resolve_moderation_appeal(
    *,
    clinic_id: UUID,
    appeal_id: UUID,
    reviewer_user: AbstractBaseUser,
    accept_appeal: bool,
    reviewer_notes: str,
) -> ModerationAppeal:
    """Review an appeal and restore content/memberships if upheld (procedente)."""
    if not can_access_moderation_console(user=reviewer_user, clinic_id=clinic_id):
        raise PermissionError("User is not authorized to review moderation appeals.")

    appeal = ModerationAppeal.objects.for_clinic(clinic_id).get(id=appeal_id)
    if appeal.status != AppealStatus.PENDING.value:
        raise ValueError("Appeal is not pending.")

    case = appeal.case

    appeal.reviewer = cast(Any, reviewer_user)
    appeal.reviewer_notes = reviewer_notes
    appeal.resolved_at = timezone.now()

    if accept_appeal:
        appeal.status = AppealStatus.ACCEPTED.value
        appeal.reviewer_decision = "UPHELD_RESTORED"

        # Redress & restoration
        if case.target_type == "post":
            CommunityPost.objects.for_clinic(clinic_id).filter(
                id=case.target_id
            ).update(status=ContentStatus.PUBLISHED.value)
        elif case.target_type == "comment":
            CommunityComment.objects.for_clinic(clinic_id).filter(
                id=case.target_id
            ).update(status=ContentStatus.PUBLISHED.value)
        # Re-instate memberships if they were suspended
        CommunityMembership.objects.for_clinic(clinic_id).filter(
            user=case.reported_user,
            status=MembershipStatus.SUSPENDED.value,
        ).update(status=MembershipStatus.ACTIVE.value)

        case.status = ModerationStatus.RESOLVED.value
    else:
        appeal.status = AppealStatus.REJECTED.value
        appeal.reviewer_decision = "DENIED_SANCTION_UPHELD"
        case.status = ModerationStatus.RESOLVED.value

    appeal.save(
        update_fields=[
            "reviewer",
            "reviewer_notes",
            "reviewer_decision",
            "status",
            "resolved_at",
            "updated_at",
        ]
    )
    case.save(update_fields=["status", "updated_at"])

    ModerationAuditTrail.objects.for_clinic(clinic_id).create(
        clinic_id=clinic_id,
        case=case,
        actor=cast(Any, reviewer_user),
        action_name=f"APPEAL_RESOLVED_{appeal.status.upper()}",
        previous_status=ModerationStatus.APPEALED.value,
        new_status=ModerationStatus.RESOLVED.value,
        details=f"Decision: {appeal.reviewer_decision}. Notes: {reviewer_notes}",
    )

    moderation_appeal_resolved.send(
        sender=ModerationAppeal,
        appeal_id=appeal.id,
        status=appeal.status,
    )
    return appeal

