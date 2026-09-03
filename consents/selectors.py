"""Authorized read selectors for current consent documents."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from clinics.policies import has_active_clinic_role
from core.selectors import Selector as Selector

from .integrity import require_document_integrity
from .models import ConsentDocument, ConsentManifestation

__all__ = ["Selector", "current_documents_for_actor"]

_ROLE_VALUES = ("clinic_admin", "therapist", "administrative_staff", "patient")


def _actor_roles(*, clinic_id: UUID, actor: AbstractBaseUser) -> set[str]:
    actor_id = actor.pk
    if not isinstance(actor_id, UUID) or not actor.is_active:
        return set()
    today = timezone.localdate()
    return {
        role
        for role in _ROLE_VALUES
        if has_active_clinic_role(
            clinic_id=clinic_id,
            user_id=actor_id,
            role=role,
            on_date=today,
        )
    }


def _audiences(roles: set[str]) -> set[str]:
    values = {str(ConsentDocument.Audience.ALL)}
    if "patient" in roles:
        values.add(str(ConsentDocument.Audience.PATIENT))
    if "therapist" in roles:
        values.add(str(ConsentDocument.Audience.PROFESSIONAL))
    if roles.intersection({"clinic_admin", "administrative_staff"}):
        values.add(str(ConsentDocument.Audience.ADMINISTRATIVE))
    return values


def current_documents_for_actor(
    *, clinic_id: UUID, actor: AbstractBaseUser
) -> list[ConsentDocument]:
    """Return only the newest effective version for each visible purpose."""
    roles = _actor_roles(clinic_id=clinic_id, actor=actor)
    if not roles:
        raise PermissionDenied("É necessário possuir acesso ativo à clínica.")
    now = timezone.now()
    candidates = list(
        ConsentDocument.objects.for_clinic(clinic_id).order_by(
            "document_type",
            "purpose",
            "audience",
            "-published_at",
            "-created_at",
        )
    )
    for document in candidates:
        require_document_integrity(document)
    visible = (
        document
        for document in candidates
        if document.audience in _audiences(roles)
        and document.is_active
        and document.published_at is not None
        and document.effective_from <= now
        and (document.effective_until is None or document.effective_until >= now)
    )
    current: list[ConsentDocument] = []
    seen: set[tuple[str, str, str]] = set()
    for document in visible:
        key = (document.document_type, document.purpose, document.audience)
        if key not in seen:
            seen.add(key)
            current.append(document)
    return current


def has_published_documents(*, clinic_id: UUID) -> bool:
    """Return whether at least one active consent document was published."""
    return (
        ConsentDocument.objects.for_clinic(clinic_id)
        .filter(is_active=True, published_at__isnull=False)
        .exists()
    )


def accepted_consent_subject_ids(
    *, clinic_id: UUID, subject_ids: set[UUID]
) -> frozenset[UUID]:
    """Return subject IDs with at least one accepted consent manifestation."""
    if not subject_ids:
        return frozenset()
    return frozenset(
        ConsentManifestation.objects.for_clinic(clinic_id)
        .filter(
            subject_id__in=subject_ids,
            decision=ConsentManifestation.Decision.ACCEPTED,
        )
        .values_list("subject_id", flat=True)
    )


__all__ = [
    "Selector",
    "accepted_consent_subject_ids",
    "current_documents_for_actor",
    "has_published_documents",
]
