"""Contracts and domain types for support network (8.16)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RelationshipType(StrEnum):
    FAMILY = "family"
    FRIEND = "friend"
    LEGAL_GUARDIAN = "legal_guardian"
    PEER = "peer"
    OTHER = "other"


class SupportPermissionScope(StrEnum):
    VIEW_WELLNESS_SUMMARY = "view_wellness_summary"
    RECEIVE_URGENT_ALERTS = "receive_urgent_alerts"
    VIEW_RELAPSE_PLAN_SAFE = "view_relapse_plan_safe"
    RECEIVE_CHECKIN_SUMMARY = "receive_checkin_summary"


FORBIDDEN_SUPPORT_SCOPES = {
    "medical_records",
    "clinical_messages",
    "instrument_results",
    "prescriptions",
    "diagnostic_hypotheses",
}


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AgeTier(StrEnum):
    CHILD = "child"  # < 12
    YOUNG_TEEN = "young_teen"  # 12-15
    OLDER_TEEN = "older_teen"  # 16-17
    ADULT = "adult"  # 18+


class GuardianVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REVOKED = "revoked"
    DISPUTED = "disputed"


class SpiritualityTradition(StrEnum):
    SECULAR = "secular"
    INTERFAITH = "interfaith"
    BUDDHIST = "buddhist"
    CHRISTIAN = "christian"
    INDIGENOUS = "indigenous"
    AFRO_BRAZILIAN = "afro_brazilian"
    SPIRITIST = "spiritist"
    OTHER = "other"


class ContemplativeCategory(StrEnum):
    BREATH_AWARENESS = "breath_awareness"
    MINDFUL_WALK = "mindful_walk"
    GRATITUDE = "gratitude"
    VALUES_REFLECTION = "values_reflection"
    LOVING_KINDNESS = "loving_kindness"
    MEDITATION = "meditation"


class EditorialReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class UrgentActionPreview:
    """Preview structure shown before an urgent action is explicitly confirmed."""

    contact_id: UUID
    contact_name: str
    contact_phone: str
    message_content: str
    requires_explicit_confirmation: bool
    disclaimer: str
