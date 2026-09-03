"""Selectors for the editorial content and learning domains."""

from __future__ import annotations

from uuid import UUID

from django.utils import timezone

from core.selectors import Selector as Selector

from .models import (
    Certificate,
    Content,
    ContentNotification,
    ContentStatus,
    ContentVersion,
    ContentVersionComment,
    Enrollment,
    Lesson,
    LessonCompletion,
    LessonFavorite,
    PrivateNote,
)


def active_enrollment_for_user(
    *, clinic_id: UUID, course_id: UUID, user_id: UUID
) -> Enrollment | None:
    """Return one tenant-local enrollment only while learner access is active."""
    return (
        Enrollment.infrastructure_objects.filter(clinic_id=clinic_id)
        .filter(course_id=course_id, user_id=user_id, ended_at__isnull=True)
        .first()
    )


def course_is_completed_for_user(
    *, clinic_id: UUID, course_id: UUID, user_id: UUID
) -> bool:
    """Report completion from server-owned published-lesson records."""
    total = (
        Lesson.infrastructure_objects.filter(clinic_id=clinic_id)
        .filter(module__course_id=course_id, status="published")
        .count()
    )
    completed = (
        LessonCompletion.infrastructure_objects.filter(clinic_id=clinic_id)
        .filter(
            lesson__module__course_id=course_id,
            lesson__status="published",
            user_id=user_id,
        )
        .count()
    )
    return total > 0 and total == completed


def active_certificate_for_user(
    *, clinic_id: UUID, course_id: UUID, user_id: UUID
) -> Certificate | None:
    """Return the participant's current non-revoked tenant certificate."""
    return (
        Certificate.infrastructure_objects.filter(clinic_id=clinic_id)
        .filter(course_id=course_id, user_id=user_id, revoked_at__isnull=True)
        .first()
    )


def certificate_by_public_code(public_code: str) -> Certificate | None:
    """Return one certificate by its public verification code, or None."""
    return Certificate.infrastructure_objects.filter(public_code=public_code).first()


def published_content_by_slug(*, clinic_id: UUID, slug: str) -> Content | None:
    """Return a published, unexpired content item for one tenant, or None."""
    content = Content.infrastructure_objects.filter(
        clinic_id=clinic_id, slug=slug, status=ContentStatus.PUBLISHED
    ).first()
    if content is None:
        return None
    if content.valid_until is not None and content.valid_until < timezone.localdate():
        return None
    return content


def published_content_by_id(*, clinic_id: UUID, content_id: UUID) -> Content | None:
    """Return a published content item by id for one tenant, or None."""
    content = Content.infrastructure_objects.filter(
        clinic_id=clinic_id, pk=content_id, status=ContentStatus.PUBLISHED
    ).first()
    if content is None:
        return None
    if content.valid_until is not None and content.valid_until < timezone.localdate():
        return None
    return content


def current_version_body(*, clinic_id: UUID, content: Content) -> str:
    """Return the sanitized body of the current published version."""
    version = ContentVersion.infrastructure_objects.filter(
        clinic_id=clinic_id, content_id=content.pk, version=content.current_version
    ).first()
    return version.body if version is not None else ""


def editorial_contents(*, clinic_id: UUID) -> list[Content]:
    """Return all tenant-local content for the editorial dashboard."""
    return list(Content.objects.for_clinic(clinic_id).order_by("-updated_at", "title"))


def editorial_content_by_id(*, clinic_id: UUID, content_id: UUID) -> Content | None:
    """Return one tenant-local editorial item without exposing foreign IDs."""
    return Content.objects.for_clinic(clinic_id).filter(pk=content_id).first()


def editorial_versions(*, clinic_id: UUID, content_id: UUID) -> list[ContentVersion]:
    """Return the immutable version history for one tenant-local content item."""
    return list(
        ContentVersion.objects.for_clinic(clinic_id)
        .filter(content_id=content_id)
        .order_by("version")
    )


def editorial_version(
    *, clinic_id: UUID, content_id: UUID, version: int
) -> ContentVersion | None:
    """Return one tenant-local content version."""
    return (
        ContentVersion.objects.for_clinic(clinic_id)
        .filter(content_id=content_id, version=version)
        .first()
    )


def editorial_comments(
    *, clinic_id: UUID, content_version_id: UUID
) -> list[ContentVersionComment]:
    """Return append-only comments in their original timeline order."""
    return list(
        ContentVersionComment.objects.for_clinic(clinic_id)
        .filter(content_version_id=content_version_id)
        .select_related("author")
        .order_by("created_at", "pk")
    )


def notifications_for_user(
    *, clinic_id: UUID, user_id: UUID
) -> list[ContentNotification]:
    """Return the requesting user's own in-product notifications, newest first."""
    return list(
        ContentNotification.infrastructure_objects.filter(
            clinic_id=clinic_id, recipient_id=user_id
        ).order_by("-created_at", "-pk")
    )


def learning_export_records(
    *, clinic_id: UUID, subject_id: UUID
) -> list[dict[str, object]]:
    """Return the subject's own favorites and private notes for DSAR export."""
    favorites = LessonFavorite.infrastructure_objects.filter(
        clinic_id=clinic_id, user_id=subject_id
    ).order_by("created_at", "id")
    notes = PrivateNote.infrastructure_objects.filter(
        clinic_id=clinic_id, author_id=subject_id
    ).order_by("created_at", "id")
    records: list[dict[str, object]] = []
    for favorite in favorites:
        records.append(
            {
                "type": "lesson_favorite",
                "clinic": str(clinic_id),
                "lesson_id": str(favorite.lesson_id),
                "active": favorite.active,
                "created_at": favorite.created_at.isoformat(),
            }
        )
    for note in notes:
        records.append(
            {
                "type": "lesson_private_note",
                "clinic": str(clinic_id),
                "lesson_id": str(note.lesson_id),
                "body": note.body,
                "created_at": note.created_at.isoformat(),
            }
        )
    return records


__all__ = [
    "Selector",
    "active_certificate_for_user",
    "active_enrollment_for_user",
    "certificate_by_public_code",
    "course_is_completed_for_user",
    "current_version_body",
    "editorial_comments",
    "editorial_content_by_id",
    "editorial_contents",
    "editorial_version",
    "editorial_versions",
    "learning_export_records",
    "notifications_for_user",
    "published_content_by_id",
    "published_content_by_slug",
]
