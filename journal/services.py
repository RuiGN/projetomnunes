"""Transactional services for the journal domain."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.services import Service as Service
from people.selectors import linked_patients_for_therapist, patient_profile_for_user

from .events import (
    daily_checkin_submitted,
    daily_checkin_updated,
    human_triage_item_created,
    human_triage_item_reviewed,
    journal_entry_access_requested,
    journal_entry_created,
    journal_entry_sharing_granted,
    journal_entry_sharing_revoked,
    journal_entry_updated,
    journal_entry_visibility_changed,
)
from .models import (
    CONTEXT_MAX_LENGTH,
    DEFAULT_CHECKIN_QUESTIONS,
    DETAIL_MAX_LENGTH,
    CheckInQuestionnaire,
    ClinicalSignalRule,
    DailyCheckIn,
    HumanTriageItem,
    JournalAccessRequest,
    JournalEntry,
)

__all__ = [
    "Service",
    "configure_checkin_questionnaire",
    "create_journal_entry",
    "get_or_create_default_checkin_questionnaire",
    "request_journal_entry_access",
    "respond_journal_entry_access_request",
    "revoke_journal_entry_sharing",
    "save_draft_daily_checkin",
    "set_journal_entry_visibility",
    "submit_daily_checkin",
    "update_journal_entry",
]


def _resolve_owned_profile_id(
    *, clinic_id: UUID, actor: AbstractBaseUser, patient_profile_id: UUID
) -> UUID:
    """Authorize self-service journal access to one patient's own profile."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None or profile.pk != patient_profile_id:
        raise PermissionDenied
    return profile.pk


def _normalized_emotions(emotions: list[str]) -> list[str]:
    normalized = sorted({item.strip() for item in emotions if item and item.strip()})
    if any(item not in JournalEntry.Emotion.values for item in normalized):
        raise ValidationError("Selecione emoções válidas.")
    return normalized


def _validate_text_lengths(
    *, context: str, triggers: str, reactions: str, strategies: str
) -> None:
    """Enforce the backend text limits with PT-BR messages."""
    if len(context) > CONTEXT_MAX_LENGTH:
        raise ValidationError(
            f"O relato do diário deve ter no máximo {CONTEXT_MAX_LENGTH} caracteres."
        )
    bounded = (
        ("gatilhos", triggers),
        ("reações", reactions),
        ("estratégias", strategies),
    )
    for label, value in bounded:
        if len(value) > DETAIL_MAX_LENGTH:
            raise ValidationError(
                f"O campo {label} deve ter no máximo {DETAIL_MAX_LENGTH} caracteres."
            )


@transaction.atomic
def create_journal_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    mood: int,
    emotions: list[str],
    intensity: int,
    context: str,
    triggers: str,
    reactions: str,
    strategies: str,
    visibility: str,
    request_id: UUID,
) -> JournalEntry:
    """Create one patient-owned diary record with per-item visibility."""
    profile_id = _resolve_owned_profile_id(
        clinic_id=clinic_id, actor=actor, patient_profile_id=patient_profile_id
    )
    if mood not in JournalEntry.Mood.values:
        raise ValidationError("Selecione um humor válido.")
    if intensity < 1 or intensity > 5:
        raise ValidationError("A intensidade deve estar entre 1 e 5.")
    if visibility not in JournalEntry.Visibility.values:
        raise ValidationError("Selecione uma visibilidade válida.")
    normalized_context = context.strip()
    if not normalized_context:
        raise ValidationError("Descreva o registro do diário.")
    normalized_triggers = triggers.strip()
    normalized_reactions = reactions.strip()
    normalized_strategies = strategies.strip()
    _validate_text_lengths(
        context=normalized_context,
        triggers=normalized_triggers,
        reactions=normalized_reactions,
        strategies=normalized_strategies,
    )
    entry = JournalEntry(
        clinic_id=clinic_id,
        author_id=actor.pk,
        patient_profile_id=profile_id,
        mood=mood,
        emotions=_normalized_emotions(emotions),
        intensity=intensity,
        context=normalized_context,
        triggers=normalized_triggers,
        reactions=normalized_reactions,
        strategies=normalized_strategies,
        visibility=visibility,
    )
    entry.full_clean(validate_unique=False, validate_constraints=False)
    entry.save(force_insert=True)
    journal_entry_created.send(
        sender=JournalEntry,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(entry.pk),
        request_id=request_id,
    )
    return entry


@transaction.atomic
def update_journal_entry(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    journal_entry_id: UUID,
    mood: int,
    emotions: list[str],
    intensity: int,
    context: str,
    triggers: str,
    reactions: str,
    strategies: str,
    request_id: UUID,
) -> JournalEntry:
    """Edit one patient-owned diary record within its authorship scope."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    entry = (
        JournalEntry.infrastructure_objects.select_for_update()
        .filter(pk=journal_entry_id, clinic_id=clinic_id, author_id=actor.pk)
        .first()
    )
    if entry is None:
        raise PermissionDenied
    if mood not in JournalEntry.Mood.values:
        raise ValidationError("Selecione um humor válido.")
    if intensity < 1 or intensity > 5:
        raise ValidationError("A intensidade deve estar entre 1 e 5.")
    normalized_context = context.strip()
    if not normalized_context:
        raise ValidationError("Descreva o registro do diário.")
    normalized_triggers = triggers.strip()
    normalized_reactions = reactions.strip()
    normalized_strategies = strategies.strip()
    _validate_text_lengths(
        context=normalized_context,
        triggers=normalized_triggers,
        reactions=normalized_reactions,
        strategies=normalized_strategies,
    )
    entry.mood = mood
    entry.emotions = _normalized_emotions(emotions)
    entry.intensity = intensity
    entry.context = normalized_context
    entry.triggers = normalized_triggers
    entry.reactions = normalized_reactions
    entry.strategies = normalized_strategies
    entry.full_clean(validate_unique=False, validate_constraints=False)
    entry.save()
    journal_entry_updated.send(
        sender=JournalEntry,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(entry.pk),
        request_id=request_id,
    )
    return entry


@transaction.atomic
def set_journal_entry_visibility(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    journal_entry_id: UUID,
    visibility: str,
    request_id: UUID,
    purpose: str = "Acompanhamento terapêutico",
) -> JournalEntry:
    """Change one owned diary record's sharing state and audit the transition."""
    if visibility not in JournalEntry.Visibility.values:
        raise ValidationError("Selecione uma visibilidade válida.")
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="patient",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied
    entry = (
        JournalEntry.infrastructure_objects.select_for_update()
        .filter(pk=journal_entry_id, clinic_id=clinic_id, author_id=actor.pk)
        .first()
    )
    if entry is None:
        raise PermissionDenied

    old_visibility = entry.visibility
    entry.visibility = visibility
    entry.save(update_fields=("visibility", "updated_at"))

    # If made private, immediately revoke any granted access requests
    if visibility == JournalEntry.Visibility.PRIVATE:
        active_reqs = (
            JournalAccessRequest.infrastructure_objects.select_for_update().filter(
                clinic_id=clinic_id,
                journal_entry_id=entry.pk,
                status=JournalAccessRequest.Status.GRANTED,
                revoked_at__isnull=True,
            )
        )
        now = timezone.now()
        for req in active_reqs:
            req.status = JournalAccessRequest.Status.REVOKED
            req.revoked_at = now
            req.revocation_reason = "Registro marcado como privado pelo paciente."
            req.save(
                update_fields=(
                    "status",
                    "revoked_at",
                    "revocation_reason",
                    "updated_at",
                )
            )

        journal_entry_sharing_revoked.send(
            sender=JournalEntry,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(entry.pk),
            request_id=request_id,
        )
    elif (
        visibility == JournalEntry.Visibility.SHAREABLE
        and old_visibility != JournalEntry.Visibility.SHAREABLE
    ):
        journal_entry_sharing_granted.send(
            sender=JournalEntry,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(entry.pk),
            purpose=purpose,
            consent_version="v1.0",
            request_id=request_id,
        )

    journal_entry_visibility_changed.send(
        sender=JournalEntry,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(entry.pk),
        request_id=request_id,
    )
    return entry


@transaction.atomic
def request_journal_entry_access(
    *,
    clinic_id: UUID,
    therapist: AbstractBaseUser,
    journal_entry_id: UUID,
    purpose: str,
    expires_at: datetime | None,
    request_id: UUID,
) -> JournalAccessRequest:
    """Therapist requests access to a confirmation-required (Amarelo) diary record."""
    today = timezone.localdate()
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=therapist.pk,
        role="therapist",
        on_date=today,
    ):
        raise PermissionDenied

    entry = (
        JournalEntry.infrastructure_objects.select_for_update()
        .filter(pk=journal_entry_id, clinic_id=clinic_id)
        .first()
    )
    if (
        entry is None
        or entry.visibility != JournalEntry.Visibility.CONFIRMATION_REQUIRED
    ):
        raise PermissionDenied

    # Check active care relationship between therapist and patient
    linked = linked_patients_for_therapist(
        clinic_id=clinic_id, therapist_id=therapist.pk, on_date=today
    )
    if entry.patient_profile_id not in {row.patient_profile_id for row in linked}:
        raise PermissionDenied

    clean_purpose = purpose.strip()
    if not clean_purpose:
        raise ValidationError("Informe a finalidade da solicitação de acesso.")

    # Expire or replace older pending requests for the same entry & therapist
    JournalAccessRequest.infrastructure_objects.filter(
        clinic_id=clinic_id,
        journal_entry_id=entry.pk,
        therapist_id=therapist.pk,
        status=JournalAccessRequest.Status.PENDING,
    ).update(
        status=JournalAccessRequest.Status.EXPIRED,
        updated_at=timezone.now(),
    )

    req = JournalAccessRequest(
        clinic_id=clinic_id,
        journal_entry_id=entry.pk,
        patient_profile_id=entry.patient_profile_id,
        therapist_id=therapist.pk,
        purpose=clean_purpose,
        consent_version="v1.0",
        status=JournalAccessRequest.Status.PENDING,
        expires_at=expires_at,
    )
    req.save(force_insert=True)

    journal_entry_access_requested.send(
        sender=JournalAccessRequest,
        clinic_id=clinic_id,
        actor_id=therapist.pk,
        resource_id=str(req.pk),
        request_id=request_id,
    )
    return req


@transaction.atomic
def respond_journal_entry_access_request(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    access_request_id: UUID,
    approved: bool,
    expires_at: datetime | None = None,
    request_id: UUID,
) -> JournalAccessRequest:
    """Patient approves or rejects a therapist's access request for an Amarelo entry."""
    req = (
        JournalAccessRequest.infrastructure_objects.select_for_update()
        .filter(pk=access_request_id, clinic_id=clinic_id)
        .first()
    )
    if req is None:
        raise PermissionDenied

    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None or profile.pk != req.patient_profile_id:
        raise PermissionDenied

    if req.status != JournalAccessRequest.Status.PENDING:
        raise ValidationError("Esta solicitação já foi respondida ou expirou.")

    now = timezone.now()
    req.responded_at = now
    if approved:
        req.status = JournalAccessRequest.Status.GRANTED
        if expires_at is not None:
            req.expires_at = expires_at
        journal_entry_sharing_granted.send(
            sender=JournalAccessRequest,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(req.journal_entry_id),
            purpose=req.purpose,
            consent_version=req.consent_version,
            request_id=request_id,
        )
    else:
        req.status = JournalAccessRequest.Status.REJECTED

    req.save(
        update_fields=(
            "status",
            "responded_at",
            "expires_at",
            "updated_at",
        )
    )
    return req


@transaction.atomic
def revoke_journal_entry_sharing(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    journal_entry_id: UUID,
    reason: str = "Revogado pelo paciente",
    request_id: UUID,
) -> JournalEntry:
    """Patient immediately revokes all sharing on one diary record."""
    return set_journal_entry_visibility(
        clinic_id=clinic_id,
        actor=actor,
        journal_entry_id=journal_entry_id,
        visibility=JournalEntry.Visibility.PRIVATE,
        request_id=request_id,
        purpose=reason,
    )


@transaction.atomic
def get_or_create_default_checkin_questionnaire(
    *, clinic_id: UUID, actor: AbstractBaseUser, request_id: UUID
) -> CheckInQuestionnaire:
    """Ensure one clinic has the default active daily check-in questionnaire."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied

    existing = (
        CheckInQuestionnaire.infrastructure_objects.filter(
            clinic_id=clinic_id, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    if existing is not None:
        return existing

    questionnaire = CheckInQuestionnaire(
        clinic_id=clinic_id,
        title="Check-in Diário",
        version="v1.0",
        is_active=True,
        questions=DEFAULT_CHECKIN_QUESTIONS,
    )
    questionnaire.full_clean(validate_unique=False, validate_constraints=False)
    questionnaire.save(force_insert=True)
    return questionnaire


@transaction.atomic
def configure_checkin_questionnaire(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    questions: list[dict[str, object]],
    title: str,
    version: str,
    request_id: UUID,
) -> CheckInQuestionnaire:
    """Create a new versioned questionnaire and deactivate the previous active one."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied

    clean_title = title.strip()
    clean_version = version.strip()
    if not clean_title:
        raise ValidationError("Informe o título do questionário.")
    if not clean_version:
        raise ValidationError("Informe a versão do questionário.")
    if not isinstance(questions, list) or not questions:
        raise ValidationError("O questionário deve conter pelo menos uma pergunta.")

    seen_keys: set[str] = set()
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            raise ValidationError("Formato inválido de pergunta.")
        key = str(question.get("key", "")).strip()
        if not key:
            raise ValidationError("Cada pergunta precisa de um identificador (key).")
        if key in seen_keys:
            raise ValidationError(
                "Cada pergunta deve ter um identificador único (key)."
            )
        seen_keys.add(key)
        if str(question.get("type", "")) not in {"scale_1_5", "text", "yes_no"}:
            raise ValidationError(
                "Tipo de pergunta inválido. Use scale_1_5, text ou yes_no."
            )
        question["order"] = question.get("order", index + 1)

    # Deactivate previous version, preserving historical interpretation
    CheckInQuestionnaire.infrastructure_objects.select_for_update().filter(
        clinic_id=clinic_id, is_active=True
    ).update(is_active=False, updated_at=timezone.now())

    questionnaire = CheckInQuestionnaire(
        clinic_id=clinic_id,
        title=clean_title,
        version=clean_version,
        is_active=True,
        questions=questions,
    )
    questionnaire.full_clean(validate_unique=False, validate_constraints=False)
    questionnaire.save(force_insert=True)
    return questionnaire


def _validate_checkin_answers(
    *, questions: list[dict[str, object]], answers: dict[str, object]
) -> dict[str, object]:
    """Validate one answer payload against the questionnaire questions."""
    validated: dict[str, object] = {}
    for question in questions:
        key = str(question.get("key", ""))
        q_type = str(question.get("type", ""))
        required = bool(question.get("required", False))
        raw = answers.get(key)

        if raw is None or raw == "":
            if required and str(raw).strip() == "" and raw is None:
                raise ValidationError(f"Responda à pergunta: {question.get('label')}")
            validated[key] = None
            continue

        if q_type == "scale_1_5":
            try:
                value = int(str(raw))
            except ValueError:
                raise ValidationError(
                    f"Resposta inválida para: {question.get('label')}"
                ) from None
            if value not in (1, 2, 3, 4, 5):
                raise ValidationError(
                    f"Resposta deve estar entre 1 e 5 para: {question.get('label')}"
                )
            validated[key] = value
        elif q_type == "yes_no":
            if raw not in ("yes", "no", "prefer_not_to_answer"):
                raise ValidationError(
                    f"Resposta inválida para: {question.get('label')}"
                )
            validated[key] = raw
        else:
            text = str(raw).strip()[:DETAIL_MAX_LENGTH]
            validated[key] = text
    return validated


def _checkin_window_start(period: str, now: datetime) -> datetime:
    """Return the start of the current edition window for idempotency checks."""
    del period
    local_now = timezone.localtime(now)
    window_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return timezone.make_aware(
        datetime.combine(
            window_start.date(), window_start.timetz().replace(tzinfo=None)
        )
    )


@transaction.atomic
def submit_daily_checkin(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    answers: dict[str, object],
    period: str = "daily",
    idempotency_key: str = "",
    request_id: UUID,
) -> DailyCheckIn:
    """Create or update one patient's daily check-in idempotently per period."""
    profile_id = _resolve_owned_profile_id(
        clinic_id=clinic_id, actor=actor, patient_profile_id=patient_profile_id
    )
    questionnaire = (
        CheckInQuestionnaire.infrastructure_objects.filter(
            clinic_id=clinic_id, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    if questionnaire is None:
        raise ValidationError("Nenhum questionário de check-in está ativo.")
    if not questionnaire.is_active:
        raise ValidationError("O questionário de check-in está desativado.")

    validated_answers = _validate_checkin_answers(
        questions=questionnaire.questions, answers=answers
    )

    now = timezone.now()
    today = timezone.localdate()
    existing = (
        DailyCheckIn.infrastructure_objects.select_for_update()
        .filter(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            date=today,
            period=period,
        )
        .first()
    )

    if (
        existing is not None
        and existing.idempotency_key
        and idempotency_key
        and existing.idempotency_key == idempotency_key
    ):
        return existing

    if existing is None:
        checkin = DailyCheckIn(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            author_id=actor.pk,
            questionnaire=questionnaire,
            questionnaire_version=questionnaire.version,
            date=today,
            period=period,
            answers=validated_answers,
            visibility=JournalEntry.Visibility.PRIVATE,
            is_draft=False,
            idempotency_key=idempotency_key,
            submitted_at=now,
        )
        checkin.full_clean(validate_unique=False, validate_constraints=False)
        checkin.save(force_insert=True)
        daily_checkin_submitted.send(
            sender=DailyCheckIn,
            clinic_id=clinic_id,
            actor_id=actor.pk,
            resource_id=str(checkin.pk),
            request_id=request_id,
        )
        return checkin

    # Same-period edit: preserve previous version for audit trail
    previous = existing.answers
    existing.answers = validated_answers
    existing.questionnaire = questionnaire
    existing.questionnaire_version = questionnaire.version
    existing.idempotency_key = idempotency_key
    existing.submitted_at = now
    existing.previous_version_answers = previous
    existing.is_draft = False
    existing.save(
        update_fields=(
            "answers",
            "questionnaire",
            "questionnaire_version",
            "submitted_at",
            "previous_version_answers",
            "is_draft",
            "updated_at",
        )
    )
    daily_checkin_updated.send(
        sender=DailyCheckIn,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(existing.pk),
        request_id=request_id,
    )
    return existing


@transaction.atomic
def save_draft_daily_checkin(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    answers: dict[str, object],
    period: str = "daily",
    request_id: UUID,
) -> DailyCheckIn:
    """Persist a partially filled check-in for later resumption."""
    profile_id = _resolve_owned_profile_id(
        clinic_id=clinic_id, actor=actor, patient_profile_id=patient_profile_id
    )
    questionnaire = (
        CheckInQuestionnaire.infrastructure_objects.filter(
            clinic_id=clinic_id, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    if questionnaire is None:
        raise ValidationError("Nenhum questionário de check-in está ativo.")

    existing = (
        DailyCheckIn.infrastructure_objects.select_for_update()
        .filter(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            date=timezone.localdate(),
            period=period,
        )
        .first()
    )
    if existing is None:
        checkin = DailyCheckIn(
            clinic_id=clinic_id,
            patient_profile_id=profile_id,
            author_id=actor.pk,
            questionnaire=questionnaire,
            questionnaire_version=questionnaire.version,
            date=timezone.localdate(),
            period=period,
            answers=answers,
            visibility=JournalEntry.Visibility.PRIVATE,
            is_draft=True,
            submitted_at=None,
        )
        checkin.full_clean(validate_unique=False, validate_constraints=False)
        checkin.save(force_insert=True)
        return checkin

    existing.answers = answers
    existing.is_draft = True
    existing.save(update_fields=("answers", "is_draft", "updated_at"))
    return existing


# ---------------------------------------------------------------------------
# 8.6.5 — Human triage for configured clinical signals
# ---------------------------------------------------------------------------


def _rule_matches(operator: str, value: int, threshold: int) -> bool:
    """Deterministic comparison between one answer and a rule threshold."""
    if operator == ClinicalSignalRule.Operator.GREATER_OR_EQUAL:
        return value >= threshold
    if operator == ClinicalSignalRule.Operator.LESS_OR_EQUAL:
        return value <= threshold
    if operator == ClinicalSignalRule.Operator.EQUAL:
        return value == threshold
    return False


def evaluate_checkin_signal_rules(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    patient_profile_id: UUID,
    answers: dict[str, object],
    request_id: UUID,
) -> list[HumanTriageItem]:
    """Evaluate configured rules against one submitted check-in.

    Deterministic engine: matches answers against clinic-configured rules and
    creates human triage items ONLY. It never diagnoses, never sends clinical
    alerts automatically, and NEVER evaluates private (Vermelho) content.
    """
    today = timezone.localdate()
    rules = list(
        ClinicalSignalRule.objects.for_clinic(clinic_id)
        .active()
        .filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today),
        )
        .filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today),
        )
    )
    if not rules:
        return []

    created: list[HumanTriageItem] = []
    for rule in rules:
        raw = answers.get(rule.question_key)
        if raw is None:
            continue
        try:
            value = int(str(raw))
        except ValueError:
            continue
        if not _rule_matches(rule.operator, value, rule.threshold):
            continue

        item, item_created = HumanTriageItem.infrastructure_objects.get_or_create(
            clinic_id=clinic_id,
            patient_profile_id=patient_profile_id,
            rule=rule,
            checkin__isnull=True,
            defaults={
                "reason": (
                    f"Resposta '{rule.question_key}' ({value}) atendeu à regra"
                    f" '{rule.name}' (limiar {rule.threshold})."
                ),
                "status": HumanTriageItem.Status.PENDING,
                "is_emergency": False,
            },
        )
        if item_created:
            human_triage_item_created.send(
                sender=HumanTriageItem,
                clinic_id=clinic_id,
                actor_id=actor.pk,
                resource_id=str(item.pk),
                request_id=request_id,
            )
        created.append(item)
    return created


@transaction.atomic
def configure_clinical_signal_rule(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    name: str,
    question_key: str,
    operator: str,
    threshold: int,
    monitoring_window: str = ClinicalSignalRule.MonitoringWindow.BUSINESS_HOURS,
    valid_from: date | None = None,
    valid_until: date | None = None,
    request_id: UUID,
) -> ClinicalSignalRule:
    """Clinic admin configures one deterministic clinical signal rule."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="clinic_admin",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied

    clean_name = name.strip()
    clean_key = question_key.strip()
    if not clean_name:
        raise ValidationError("Informe o nome da regra.")
    if not clean_key:
        raise ValidationError("Informe a pergunta monitorada pela regra.")
    if operator not in ClinicalSignalRule.Operator.values:
        raise ValidationError("Operador inválido.")
    if threshold < 1 or threshold > 5:
        raise ValidationError("O limiar deve estar entre 1 e 5.")
    if monitoring_window not in ClinicalSignalRule.MonitoringWindow.values:
        raise ValidationError("Janela de monitoramento inválida.")
    if valid_from and valid_until and valid_from > valid_until:
        raise ValidationError("A data inicial deve preceder a data final.")

    rule = ClinicalSignalRule(
        clinic_id=clinic_id,
        name=clean_name,
        question_key=clean_key,
        operator=operator,
        threshold=threshold,
        is_active=True,
        monitoring_window=monitoring_window,
        valid_from=valid_from,
        valid_until=valid_until,
        authorized_by_id=actor.pk,
    )
    rule.full_clean(validate_unique=False, validate_constraints=False)
    rule.save(force_insert=True)
    return rule


@transaction.atomic
def review_human_triage_item(
    *,
    clinic_id: UUID,
    actor: AbstractBaseUser,
    triage_item_id: UUID,
    decision: str,
    request_id: UUID,
) -> HumanTriageItem:
    """A human professional reviews and closes one triage item."""
    if not has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="therapist",
        on_date=timezone.localdate(),
    ):
        raise PermissionDenied

    item = (
        HumanTriageItem.infrastructure_objects.select_for_update()
        .filter(pk=triage_item_id, clinic_id=clinic_id)
        .first()
    )
    if item is None:
        raise PermissionDenied

    clean_decision = decision.strip()
    if not clean_decision:
        raise ValidationError("Registre a decisão da revisão humana.")

    item.status = HumanTriageItem.Status.CLOSED
    item.reviewed_by_id = actor.pk
    item.reviewed_at = timezone.now()
    item.review_decision = clean_decision
    item.save(
        update_fields=(
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_decision",
            "updated_at",
        )
    )
    human_triage_item_reviewed.send(
        sender=HumanTriageItem,
        clinic_id=clinic_id,
        actor_id=actor.pk,
        resource_id=str(item.pk),
        request_id=request_id,
    )
    return item
