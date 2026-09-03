"""Selectors for the PRD 8.12.2 course authoring read paths."""

from __future__ import annotations

from uuid import UUID

from .models import Course, CourseModule, Lesson, LessonMaterial


def learning_course_by_id(*, clinic_id: UUID, course_id: UUID) -> Course | None:
    """Resolve one course strictly inside the requesting tenant."""
    return Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()


def learning_course_modules(*, clinic_id: UUID, course_id: UUID) -> list[CourseModule]:
    """Return the tenant course modules in stable (position, id) order."""
    return list(
        CourseModule.infrastructure_objects.filter(
            clinic_id=clinic_id, course_id=course_id
        ).order_by("position", "id")
    )


def learning_module_lessons(*, clinic_id: UUID, module_id: UUID) -> list[Lesson]:
    """Return the tenant module lessons in stable (position, id) order."""
    return list(
        Lesson.infrastructure_objects.filter(
            clinic_id=clinic_id, module_id=module_id
        ).order_by("position", "id")
    )


def learning_lesson_materials(
    *, clinic_id: UUID, lesson_id: UUID
) -> list[LessonMaterial]:
    """Return the tenant lesson materials in stable (position, id) order."""
    return list(
        LessonMaterial.infrastructure_objects.filter(
            clinic_id=clinic_id, lesson_id=lesson_id
        ).order_by("position", "id")
    )
