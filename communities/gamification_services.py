"""Services for responsible, opt-in, non-punitive gamification (8.17.4)."""

from __future__ import annotations

from datetime import time
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from communities.contracts import (
    MAX_DAILY_GAMIFICATION_REMINDERS,
    SelfCareCategory,
)
from communities.events import (
    gamification_history_purged,
    gamification_opted_in,
    gamification_paused,
    gamification_progress_logged,
)
from communities.gamification_models import (
    GamificationMilestone,
    GamificationProgress,
    ResponsibleGamificationProfile,
)


@transaction.atomic
def opt_in_responsible_gamification(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> ResponsibleGamificationProfile:
    """Explicit opt-in to non-punitive self-care milestones (disabled by default)."""
    profile, created = ResponsibleGamificationProfile.objects.for_clinic(
        clinic_id
    ).get_or_create(
        user=cast(Any, user),
        defaults={
            "clinic_id": clinic_id,
            "is_opted_in": True,
            "opted_in_at": timezone.now(),
        },
    )
    if not created and not profile.is_opted_in:
        profile.is_opted_in = True
        profile.is_paused = False
        profile.opted_in_at = timezone.now()
        profile.save(
            update_fields=["is_opted_in", "is_paused", "opted_in_at", "updated_at"]
        )

    gamification_opted_in.send(
        sender=ResponsibleGamificationProfile,
        user_id=user.pk,
    )
    return profile


@transaction.atomic
def pause_responsible_gamification(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> ResponsibleGamificationProfile:
    """Pause self-care milestone tracking without any penalty or lost progress."""
    profile = ResponsibleGamificationProfile.objects.for_clinic(
        clinic_id
    ).filter(user_id=user.pk).first()
    if profile is None or not profile.is_opted_in:
        raise ValueError("Gamification is disabled. User must explicitly opt-in first.")
    profile.is_paused = True
    profile.paused_at = timezone.now()
    profile.save(update_fields=["is_paused", "paused_at", "updated_at"])

    gamification_paused.send(sender=ResponsibleGamificationProfile, user_id=user.pk)
    return profile


@transaction.atomic
def resume_responsible_gamification(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
) -> ResponsibleGamificationProfile:
    """Resume self-care milestones with zero punishment for hiatus."""
    profile = ResponsibleGamificationProfile.objects.for_clinic(
        clinic_id
    ).filter(user_id=user.pk).first()
    if profile is None or not profile.is_opted_in:
        raise ValueError("Gamification is disabled. User must explicitly opt-in first.")
    profile.is_paused = False
    profile.paused_at = None
    profile.save(update_fields=["is_paused", "paused_at", "updated_at"])
    return profile


@transaction.atomic
def configure_gamification_reminders(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    reminders_enabled: bool,
    quiet_hours_start: time | None = None,
    quiet_hours_end: time | None = None,
    max_daily_reminders: int = 3,
) -> ResponsibleGamificationProfile:
    """Configure quiet hours and frequency caps for self-care reminders."""
    capped_reminders = min(max_daily_reminders, MAX_DAILY_GAMIFICATION_REMINDERS)
    profile = ResponsibleGamificationProfile.objects.for_clinic(
        clinic_id
    ).filter(user_id=user.pk).first()
    if profile is None or not profile.is_opted_in:
        raise ValueError("Gamification is disabled. User must explicitly opt-in first.")
    profile.reminders_enabled = reminders_enabled
    profile.quiet_hours_start = quiet_hours_start
    profile.quiet_hours_end = quiet_hours_end
    profile.max_daily_reminders = capped_reminders
    profile.save(
        update_fields=[
            "reminders_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "max_daily_reminders",
            "updated_at",
        ]
    )
    return profile


@transaction.atomic
def log_self_care_milestone(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    milestone_slug: str,
) -> tuple[GamificationProgress, str]:
    """Record voluntary self-care milestone; returns the record and affirmation."""
    profile = ResponsibleGamificationProfile.objects.for_clinic(
        clinic_id
    ).filter(user_id=user.pk).first()
    if profile is None or not profile.is_opted_in:
        raise ValueError("Gamification is disabled. User must explicitly opt-in first.")
    if profile.is_paused:
        raise ValueError(
            "Gamification is currently paused. Resume to record milestones."
        )

    milestone = GamificationMilestone.objects.get(slug=milestone_slug, is_active=True)
    today = timezone.localdate()

    progress, created = GamificationProgress.objects.for_clinic(
        clinic_id
    ).get_or_create(
        user=cast(Any, user),
        milestone=milestone,
        occurred_date=today,
        defaults={
            "clinic_id": clinic_id,
            "count_today": 1,
        },
    )
    if not created:
        if progress.count_today >= milestone.daily_cap:
            msg = f"Você já atingiu o marco de hoje para {milestone.title}."
            return (
                progress,
                f"{msg} Descanse e celebre o seu momento!",
            )
        progress.count_today += 1
        progress.save(update_fields=["count_today", "updated_at"])

    gamification_progress_logged.send(
        sender=GamificationProgress,
        user_id=user.pk,
        milestone_id=milestone.id,
    )
    return progress, milestone.supportive_message


@transaction.atomic
def purge_gamification_history(
    *,
    clinic_id: UUID,
    user: AbstractBaseUser,
    opt_out: bool = True,
) -> int:
    """Immediate, permanent deletion of all gamification logs for the user."""
    deleted_count, _ = (
        GamificationProgress.objects.for_clinic(clinic_id)
        .filter(user_id=user.pk)
        .delete()
    )

    if opt_out:
        ResponsibleGamificationProfile.objects.for_clinic(clinic_id).filter(
            user_id=user.pk
        ).update(
            is_opted_in=False,
            is_paused=False,
            opted_in_at=None,
        )

    record_audit_event(
        clinic_id=clinic_id,
        actor_id=user.pk,
        action="communities.gamification_history_purged",
        resource_type="gamification_profile",
        resource_id=str(user.pk),
        outcome="success",
        request_id=uuid4(),
        network_origin=None,
    )
    gamification_history_purged.send(
        sender=ResponsibleGamificationProfile,
        user_id=user.pk,
    )
    return deleted_count


def seed_default_self_care_milestones() -> list[GamificationMilestone]:
    """Populate default vetted non-clinical self-care milestone catalog."""
    defaults = [
        {
            "category": SelfCareCategory.HYDRATION.value,
            "slug": "copo-de-agua",
            "title": "Pausa para Hidratação",
            "description": "Beber um copo de água com atenção plena ao próprio corpo.",
            "daily_cap": 4,
            "supportive_message": "Hidratar-se é um gesto simples de cuidado com você.",
        },
        {
            "category": SelfCareCategory.BREATHING.value,
            "slug": "respiro-consciente",
            "title": "Três Respirações Conscientes",
            "description": "Pausa de 1 minuto para inspirar e expirar com calma.",
            "daily_cap": 3,
            "supportive_message": "Inspirar e soltar o ar. O presente é o seu refúgio.",
        },
        {
            "category": SelfCareCategory.REFLECTION.value,
            "slug": "momento-gentileza",
            "title": "Gentileza Consigo",
            "description": "Reconhecer um pequeno esforço positivo hoje, sem cobrança.",
            "daily_cap": 1,
            "supportive_message": "Você fez o melhor possível hoje. Isso já basta.",
        },
        {
            "category": SelfCareCategory.ROUTINE.value,
            "slug": "alongamento-suave",
            "title": "Alongamento Suave",
            "description": "Movimentar ombros e pescoço suavemente durante a rotina.",
            "daily_cap": 2,
            "supportive_message": "Aliviar a tensão física ajuda a mente a relaxar.",
        },
    ]
    created_milestones: list[GamificationMilestone] = []
    for data in defaults:
        milestone, _ = GamificationMilestone.objects.update_or_create(
            slug=data["slug"],
            defaults=data,
        )
        created_milestones.append(milestone)
    return created_milestones

