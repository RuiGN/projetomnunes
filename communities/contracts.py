"""Contracts, enums, and data definitions for communities and social spaces."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class GroupType(StrEnum):
    PRIVATE_INVITE_ONLY = "private_invite_only"
    INSTITUTIONAL = "institutional"
    THEMATIC_APPROVED = "thematic_approved"


class GroupVisibility(StrEnum):
    PRIVATE = "private"
    TENANT_DIRECTORY = "tenant_directory"
    HIDDEN = "hidden"


class MembershipRole(StrEnum):
    OWNER = "owner"
    MODERATOR = "moderator"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    MUTED = "muted"
    SUSPENDED = "suspended"
    LEFT = "left"
    REMOVED = "removed"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ContentStatus(StrEnum):
    PUBLISHED = "published"
    EDITED = "edited"
    HIDDEN_BY_MODERATOR = "hidden_by_moderator"
    DELETED = "deleted"


class ReactionType(StrEnum):
    SUPPORT = "support"
    HEART = "heart"
    HELPFUL = "helpful"
    THANK_YOU = "thank_you"


class ViolationCategory(StrEnum):
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    UNSAFE_CONTENT = "unsafe_content"
    SPAM = "spam"
    PRIVACY_VIOLATION = "privacy_violation"
    OTHER = "other"


class ModerationSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ModerationStatus(StrEnum):
    PENDING_TRIAGE = "pending_triage"
    IN_REVIEW = "in_review"
    ACTIONED = "actioned"
    DISMISSED = "dismissed"
    APPEALED = "appealed"
    RESOLVED = "resolved"


class ModerationDecision(StrEnum):
    NO_ACTION = "no_action"
    CONTENT_REMOVED = "content_removed"
    USER_WARNED = "user_warned"
    USER_SUSPENDED = "user_suspended"
    USER_BANNED = "user_banned"


class AppealStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SelfCareCategory(StrEnum):
    HYDRATION = "hydration"
    BREATHING = "breathing"
    REFLECTION = "reflection"
    ROUTINE = "routine"


ALLOWED_ATTACHMENT_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "application/pdf"}
)
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_SLOW_MODE_SECONDS = 30
MAX_DAILY_GAMIFICATION_REMINDERS = 5


@dataclass(frozen=True)
class ModerationTriageResult:
    case_id: UUID
    severity: ModerationSeverity
    priority_score: int
    due_at: datetime
    requires_double_review: bool
