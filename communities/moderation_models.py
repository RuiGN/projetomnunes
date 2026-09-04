"""Models for moderation, evidence vault, audit trails, and appeals (8.17.3)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from communities.community_models import (
    CommunityTenantManager,
    InfrastructureCommunityManager,
)
from communities.contracts import (
    AppealStatus,
    ModerationDecision,
    ModerationSeverity,
    ModerationStatus,
    ViolationCategory,
)
from core.persistence import UUIDTimestampedModel


class ModerationCase(UUIDTimestampedModel):
    """Case opened for reviewing suspected violations with mandatory human decision."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="moderation_cases",
    )
    target_type = models.CharField(max_length=50)  # "post", "comment", "membership"
    target_id = models.UUIDField(db_index=True)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_moderation_cases",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="moderation_cases_against",
    )
    violation_category = models.CharField(
        max_length=50,
        choices=[(c.value, c.name) for c in ViolationCategory],
        default=ViolationCategory.OTHER.value,
    )
    severity = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in ModerationSeverity],
        default=ModerationSeverity.MEDIUM.value,
    )
    priority_score = models.PositiveIntegerField(default=50)
    status = models.CharField(
        max_length=30,
        choices=[(st.value, st.name) for st in ModerationStatus],
        default=ModerationStatus.PENDING_TRIAGE.value,
    )
    assigned_moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_moderation_cases",
    )
    decision = models.CharField(
        max_length=30,
        choices=[(d.value, d.name) for d in ModerationDecision],
        null=True,
        blank=True,
    )
    justification = models.TextField(blank=True, default="")
    actioned_at = models.DateTimeField(null=True, blank=True)
    sla_deadline = models.DateTimeField()
    sla_breached = models.BooleanField(default=False)
    requires_double_review = models.BooleanField(default=False)
    second_moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="second_reviewed_moderation_cases",
    )
    second_decision = models.CharField(
        max_length=30,
        choices=[(d.value, d.name) for d in ModerationDecision],
        null=True,
        blank=True,
    )
    second_justification = models.TextField(blank=True, default="")
    second_actioned_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["ModerationCase"]()
    infrastructure_objects = InfrastructureCommunityManager["ModerationCase"]()

    class Meta:
        db_table = "communities_moderation_case"
        ordering = ["-priority_score", "sla_deadline"]
        indexes = [
            models.Index(fields=["clinic", "status", "-priority_score"]),
            models.Index(fields=["clinic", "assigned_moderator", "status"]),
            models.Index(fields=["clinic", "target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"Case {self.id} ({self.violation_category}, {self.status})"


class EvidenceVault(UUIDTimestampedModel):
    """Immutable, segregated snapshot of reported content for audit preservation."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="evidence_snapshots",
    )
    case = models.OneToOneField(
        ModerationCase,
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    content_snapshot = models.TextField()
    author_id = models.UUIDField()
    metadata_json = models.JSONField(default=dict)

    objects = CommunityTenantManager["EvidenceVault"]()
    infrastructure_objects = InfrastructureCommunityManager["EvidenceVault"]()

    class Meta:
        db_table = "communities_evidence_vault"
        indexes = [
            models.Index(fields=["clinic", "case"]),
        ]


class ModerationAuditTrail(UUIDTimestampedModel):
    """Append-only audit record for moderation state transitions and decisions."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="moderation_audit_records",
    )
    case = models.ForeignKey(
        ModerationCase,
        on_delete=models.CASCADE,
        related_name="audit_trail",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_audit_actions",
    )
    action_name = models.CharField(max_length=100)
    previous_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)
    details = models.TextField(blank=True, default="")

    objects = CommunityTenantManager["ModerationAuditTrail"]()
    infrastructure_objects = InfrastructureCommunityManager["ModerationAuditTrail"]()

    class Meta:
        db_table = "communities_moderation_audit"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["clinic", "case", "created_at"]),
        ]


class ModerationAppeal(UUIDTimestampedModel):
    """Appeal submitted by a penalized user with human review and potential redress."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="moderation_appeals",
    )
    case = models.ForeignKey(
        ModerationCase,
        on_delete=models.CASCADE,
        related_name="appeals",
    )
    appellant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submitted_moderation_appeals",
    )
    appeal_grounds = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in AppealStatus],
        default=AppealStatus.PENDING.value,
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_moderation_appeals",
    )
    reviewer_decision = models.CharField(max_length=30, blank=True, default="")
    reviewer_notes = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = CommunityTenantManager["ModerationAppeal"]()
    infrastructure_objects = InfrastructureCommunityManager["ModerationAppeal"]()

    class Meta:
        db_table = "communities_moderation_appeal"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["case", "appellant"]),
        ]
