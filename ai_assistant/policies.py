"""Authorization policies for AI assistant, drafting and governance (8.19)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from ai_assistant.models import AiAssistantRolloutFlag, AiDraftingSession
from clinics.policies import has_active_clinic_role
from core.policies import AuthorizationPolicy as CoreAuthorizationPolicy


def _is_clinical_professional(*, user_id: UUID, clinic_id: UUID) -> bool:
    today = timezone.localdate()
    return any(
        has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=user_id,
            role=role,
            on_date=today,
        )
        for role in {"therapist", "physician", "clinical_director"}
    )


def _is_clinic_admin(*, user_id: UUID, clinic_id: UUID) -> bool:
    today = timezone.localdate()
    return has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=user_id,
        role="clinic_admin",
        on_date=today,
    )


def _is_kill_switched(*, clinic_id: UUID) -> bool:
    flag = AiAssistantRolloutFlag.infrastructure_objects.filter(
        clinic_id=clinic_id
    ).first()
    return bool(flag and (flag.emergency_kill_switch or not flag.is_enabled))


class AuthorizationPolicy(CoreAuthorizationPolicy[AbstractBaseUser, Any]):
    """AI Assistant baseline authorization policy."""

    def is_allowed(self, subject: AbstractBaseUser, resource: Any, /) -> bool:
        if not subject.is_authenticated or not subject.is_active:
            return False
        clinic_id = getattr(resource, "clinic_id", None)
        if clinic_id is None:
            return False
        if _is_kill_switched(clinic_id=clinic_id):
            return False
        return _is_clinical_professional(user_id=subject.pk, clinic_id=clinic_id)


def can_use_ai_assistant(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Allow AI drafting only to authorized clinicians in enabled tenants."""
    if not user.is_authenticated or not user.is_active:
        return False
    if _is_kill_switched(clinic_id=clinic_id):
        return False
    return _is_clinical_professional(user_id=user.pk, clinic_id=clinic_id)


def can_review_ai_draft(*, user: AbstractBaseUser, session: AiDraftingSession) -> bool:
    """Allow human review only by the session author or authorized supervisor."""
    if not user.is_authenticated or not user.is_active:
        return False
    if session.author_id == user.pk:
        return True
    return _is_clinical_professional(user_id=user.pk, clinic_id=session.clinic_id)


def can_manage_ai_governance(*, user: AbstractBaseUser, clinic_id: UUID) -> bool:
    """Allow governance, benchmark runs, and kill-switch management to clinic admins."""
    if not user.is_authenticated or not user.is_active:
        return False
    return _is_clinic_admin(user_id=user.pk, clinic_id=clinic_id)
