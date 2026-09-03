"""Versioned content persistence with an explicit editorial workflow."""

from __future__ import annotations

from typing import Any, NoReturn, TypeVar
from uuid import UUID, uuid4

from django.conf import settings
from django.db import models
from django.db.models import ManyToManyField

from core.persistence import UUIDTimestampedModel

from .storage import PrivateContentStorage

_LearningT = TypeVar("_LearningT", bound="TenantLearningModel")


class ContentKind(models.TextChoices):
    ARTICLE = "article", "Artigo"
    VIDEO = "video", "Vídeo"
    AUDIO = "audio", "Áudio"
    EXERCISE = "exercise", "Exercício"


class ContentStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    REVIEW = "review", "Em revisão"
    APPROVED = "approved", "Aprovado"
    PUBLISHED = "published", "Publicado"
    ARCHIVED = "archived", "Arquivado"


def content_media_upload_to(instance: ContentMedia, filename: str) -> str:
    """Build an opaque tenant-owned private path without the supplied filename."""
    from pathlib import Path
    from uuid import uuid4

    clinic_id = getattr(instance, "clinic_id", "unknown")
    return f"content/{clinic_id}/media/{uuid4().hex}{Path(filename).suffix.lower()}"


class ContentQuerySet(models.QuerySet["Content"]):
    def for_clinic(self, clinic_id: UUID) -> ContentQuerySet:
        return self.filter(clinic_id=clinic_id)


class ContentManager(models.Manager["Content"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Content queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ContentQuerySet:
        return ContentQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureContentManager(models.Manager["Content"]):
    def get_queryset(self) -> ContentQuerySet:
        return ContentQuerySet(self.model, using=self._db)


class ContentTaxonomyQuerySet(models.QuerySet["ContentCategory"]):
    def for_clinic(self, clinic_id: UUID) -> ContentTaxonomyQuerySet:
        return self.filter(clinic_id=clinic_id)


class ContentTaxonomyManager(models.Manager):  # type: ignore[type-arg]
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Taxonomy queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ContentTaxonomyQuerySet:
        return ContentTaxonomyQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureContentTaxonomyManager(models.Manager):  # type: ignore[type-arg]
    def get_queryset(self) -> ContentTaxonomyQuerySet:
        return ContentTaxonomyQuerySet(self.model, using=self._db)


class ContentCategory(UUIDTimestampedModel):
    """One managed, tenant-scoped editorial category."""

    clinic = models.ForeignKey(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="content_categories"
    )
    name = models.CharField(max_length=64)
    slug = models.SlugField(max_length=80)
    content_items = models.ManyToManyField(
        "content.Content", related_name="content_categories", blank=True
    )

    objects = ContentTaxonomyManager()
    infrastructure_objects = InfrastructureContentTaxonomyManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "name"), name="unique_category_name_per_clinic"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ContentTag(UUIDTimestampedModel):
    """One managed, tenant-scoped editorial tag."""

    clinic = models.ForeignKey(
        "clinics.Clinic", on_delete=models.CASCADE, related_name="content_tags"
    )
    name = models.CharField(max_length=64)
    slug = models.SlugField(max_length=80)
    content_items = models.ManyToManyField(
        "content.Content", related_name="content_tags", blank=True
    )

    objects = ContentTaxonomyManager()
    infrastructure_objects = InfrastructureContentTaxonomyManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "name"), name="unique_tag_per_clinic"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Content(UUIDTimestampedModel):
    """One versioned content item owned by a single organization (tenant)."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="content_items",
    )
    slug = models.SlugField(max_length=160)
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=ContentKind.choices)
    language_code = models.CharField(max_length=10, default="pt-BR")
    category = models.CharField(max_length=64, blank=True)
    tags = models.JSONField(default=list, blank=True)
    audience = models.CharField(
        max_length=16,
        choices=(("patient", "Paciente"), ("professional", "Profissional")),
        default="patient",
    )
    contraindications = models.TextField(max_length=1000, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    valid_until = models.DateField(blank=True, null=True)
    current_version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=ContentStatus.choices, default=ContentStatus.DRAFT
    )
    successor = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_by",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="content_items_created",
    )

    objects = ContentManager()
    infrastructure_objects = InfrastructureContentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "slug"), name="unique_content_slug_per_clinic"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "kind", "status"), name="content_kind_status_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.slug} v{self.current_version}"


class ContentVersionQuerySet(models.QuerySet["ContentVersion"]):
    def for_clinic(self, clinic_id: UUID) -> ContentVersionQuerySet:
        return self.filter(clinic_id=clinic_id)


class ContentVersionManager(models.Manager["ContentVersion"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ContentVersion queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ContentVersionQuerySet:
        return ContentVersionQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureContentVersionManager(models.Manager["ContentVersion"]):
    def get_queryset(self) -> ContentVersionQuerySet:
        return ContentVersionQuerySet(self.model, using=self._db)


class ContentVersion(UUIDTimestampedModel):
    """One immutable version body with its editorial state transition."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="content_versions",
    )
    content = models.ForeignKey(
        Content,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    body = models.TextField(max_length=50000)
    status = models.CharField(max_length=16, choices=ContentStatus.choices)
    published_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    scheduled_for = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_versions_approved",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_versions_submitted",
    )
    review_opinion = models.TextField(max_length=2000, blank=True)
    review_references = models.JSONField(default=list, blank=True)
    review_evidence = models.TextField(max_length=2000, blank=True)
    review_required_specialty = models.CharField(max_length=64, blank=True)
    review_valid_until = models.DateField(blank=True, null=True)
    review_signed_digest = models.CharField(max_length=64, blank=True)
    approver_credential_snapshot = models.JSONField(default=dict, blank=True)
    body_hash = models.CharField(max_length=64, blank=True)

    objects = ContentVersionManager()
    infrastructure_objects = InfrastructureContentVersionManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("content", "version"), name="unique_version_per_content"
            ),
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "scheduled_for"),
                name="content_version_state_idx",
            ),
        ]


class ContentVersionCommentQuerySet(models.QuerySet["ContentVersionComment"]):
    """Tenant-scoped append-only editorial comment reads."""

    def for_clinic(self, clinic_id: UUID) -> ContentVersionCommentQuerySet:
        return self.filter(clinic_id=clinic_id)

    def update(self, **kwargs: object) -> NoReturn:
        raise RuntimeError("Editorial comments are append-only.")

    def delete(self) -> NoReturn:
        raise RuntimeError("Editorial comments are append-only.")


class ContentVersionCommentManager(models.Manager["ContentVersionComment"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Comment queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ContentVersionCommentQuerySet:
        return ContentVersionCommentQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureContentVersionCommentManager(
    models.Manager["ContentVersionComment"]
):
    def get_queryset(self) -> ContentVersionCommentQuerySet:
        return ContentVersionCommentQuerySet(self.model, using=self._db)


class ContentVersionComment(UUIDTimestampedModel):
    """One immutable editorial comment appended to a content version."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="content_version_comments",
    )
    content_version = models.ForeignKey(
        ContentVersion,
        on_delete=models.PROTECT,
        related_name="editorial_comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="content_version_comments",
    )
    body = models.TextField(max_length=2000)

    objects = ContentVersionCommentManager()
    infrastructure_objects = InfrastructureContentVersionCommentManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=("clinic", "content_version", "created_at"),
                name="content_comment_timeline_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        persisted = self.__class__.infrastructure_objects.filter(pk=self.pk).exists()
        if self.pk and persisted:
            raise RuntimeError("Editorial comments are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise RuntimeError("Editorial comments are append-only.")


class ContentMediaQuerySet(models.QuerySet["ContentMedia"]):
    def for_clinic(self, clinic_id: UUID) -> ContentMediaQuerySet:
        return self.filter(clinic_id=clinic_id)


class ContentMediaManager(models.Manager["ContentMedia"]):
    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ContentMedia queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ContentMediaQuerySet:
        return ContentMediaQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureContentMediaManager(models.Manager["ContentMedia"]):
    def get_queryset(self) -> ContentMediaQuerySet:
        return ContentMediaQuerySet(self.model, using=self._db)


class ContentMedia(UUIDTimestampedModel):
    """One validated private media asset attached to a content version."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="content_media",
    )
    content = models.ForeignKey(
        Content,
        on_delete=models.CASCADE,
        related_name="media_assets",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="content_media_uploaded",
    )
    file = models.FileField(
        upload_to=content_media_upload_to,
        storage=PrivateContentStorage(),
        max_length=255,
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.PositiveBigIntegerField()

    objects = ContentMediaManager()
    infrastructure_objects = InfrastructureContentMediaManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(fields=("clinic", "content"), name="content_media_idx"),
        ]


class LearningTenantQuerySet(models.QuerySet):  # type: ignore[type-arg]
    """Explicit tenant scope shared by learning-product persistence."""

    def for_clinic(self, clinic_id: UUID) -> LearningTenantQuerySet:
        return self.filter(clinic_id=clinic_id)


class LearningTenantManager(models.Manager):  # type: ignore[type-arg]
    """Fail closed when a learning model is queried without a tenant."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("Learning queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> LearningTenantQuerySet:
        return LearningTenantQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureLearningTenantManager(
    models.Manager  # type: ignore[type-arg]
):
    def get_queryset(self) -> LearningTenantQuerySet:
        return LearningTenantQuerySet(self.model, using=self._db)


class TenantLearningModel(UUIDTimestampedModel):
    """Abstract tenant-owned persistence with guarded public reads."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="content_%(class)ss",
    )

    objects = LearningTenantManager()
    infrastructure_objects = InfrastructureLearningTenantManager()

    class Meta:
        abstract = True
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"


class CourseStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PUBLISHED = "published", "Publicado"
    ARCHIVED = "archived", "Arquivado"


class Course(TenantLearningModel):
    """Versioned curriculum root with tenant-bound access requirements."""

    slug = models.SlugField(max_length=160)
    title = models.CharField(max_length=255)
    description = models.TextField(max_length=4000, blank=True)
    duration_minutes = models.PositiveIntegerField()
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courses_instructed",
    )
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT
    )
    curriculum_version = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(blank=True, null=True)
    available_from = models.DateTimeField(blank=True, null=True)
    available_until = models.DateTimeField(blank=True, null=True)
    capacity = models.PositiveIntegerField(blank=True, null=True)
    required_plan_code = models.CharField(max_length=64, blank=True)
    invitation_required = models.BooleanField(default=False)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "slug"), name="unique_course_slug_per_clinic"
            )
        ]
        indexes = [
            models.Index(fields=("clinic", "status"), name="course_clinic_status_idx")
        ]


class CourseModule(TenantLearningModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT
    )

    class Meta(TenantLearningModel.Meta):
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "position"), name="unique_module_position"
            )
        ]


class Lesson(TenantLearningModel):
    module = models.ForeignKey(
        CourseModule, on_delete=models.CASCADE, related_name="lessons"
    )
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField()
    duration_minutes = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT
    )
    transcript = models.TextField(blank=True)
    captions = models.TextField(blank=True)

    class Meta(TenantLearningModel.Meta):
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "position"), name="unique_lesson_position"
            )
        ]


class LessonMaterial(TenantLearningModel):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="materials"
    )
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=500)
    position = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT
    )

    class Meta(TenantLearningModel.Meta):
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "position"), name="unique_material_position"
            )
        ]


class CoursePrerequisite(TenantLearningModel):
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="prerequisite_links"
    )
    prerequisite_course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="required_by_links"
    )

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("course", "prerequisite_course"),
                name="unique_course_prerequisite",
            )
        ]


class LearningPath(TenantLearningModel):
    slug = models.SlugField(max_length=160)
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=CourseStatus.choices, default=CourseStatus.DRAFT
    )
    courses: ManyToManyField[Course, LearningPathCourse] = models.ManyToManyField(
        Course, through="LearningPathCourse"
    )

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "slug"), name="unique_path_slug_per_clinic"
            )
        ]


class LearningPathCourse(TenantLearningModel):
    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()

    class Meta(TenantLearningModel.Meta):
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("path", "course"), name="unique_course_per_path"
            ),
            models.UniqueConstraint(
                fields=("path", "position"), name="unique_path_course_position"
            ),
        ]


class EnrollmentSource(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    COHORT = "cohort", "Coorte"


class Enrollment(TenantLearningModel):
    """One active learner access to one tenant course."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_enrollments",
    )
    source = models.CharField(max_length=16, choices=EnrollmentSource.choices)
    idempotency_key = models.UUIDField()
    ended_at = models.DateTimeField(blank=True, null=True)
    end_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("course", "user"),
                condition=models.Q(ended_at__isnull=True),
                name="unique_active_enrollment_per_course",
            ),
            models.UniqueConstraint(
                fields=("user", "idempotency_key"),
                name="unique_enrollment_idempotency_per_user",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ended_at__isnull=True, end_reason="")
                    | (models.Q(ended_at__isnull=False) & ~models.Q(end_reason=""))
                ),
                name="enrollment_end_state_coherent",
            ),
        ]
        indexes = [
            models.Index(fields=("clinic", "course"), name="enrollment_course_idx")
        ]


class Cohort(TenantLearningModel):
    """A named tenant cohort used for coordinated enrollment."""

    name = models.CharField(max_length=255)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "name"), name="unique_cohort_name_per_clinic"
            )
        ]


class CohortMember(TenantLearningModel):
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cohort_memberships",
    )

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("cohort", "user"), name="unique_cohort_member"
            )
        ]


class QuizStatus(models.TextChoices):
    DRAFT = "draft", "Rascunho"
    PUBLISHED = "published", "Publicado"
    ARCHIVED = "archived", "Arquivado"


class Quiz(TenantLearningModel):
    """One educational assessment attached to a tenant course."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    slug = models.SlugField(max_length=160)
    title = models.CharField(max_length=255)
    minimum_grade = models.PositiveSmallIntegerField(default=70)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    shuffle_questions = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=QuizStatus.choices)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "slug"), name="unique_quiz_slug_per_clinic"
            )
        ]


class QuizQuestion(TenantLearningModel):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField(max_length=2000)
    options = models.JSONField()
    correct_key = models.CharField(max_length=16)
    explanation = models.TextField(max_length=1000, blank=True)
    position = models.PositiveIntegerField()

    class Meta(TenantLearningModel.Meta):
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("quiz", "position"), name="unique_quiz_question_position"
            )
        ]


class QuizAttempt(TenantLearningModel):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    score = models.PositiveSmallIntegerField()
    passed = models.BooleanField()
    answers = models.JSONField(default=dict, blank=True)
    request_id = models.UUIDField(default=uuid4)
    shuffle_seed = models.PositiveBigIntegerField(default=0)
    question_order = models.JSONField(default=list, blank=True)
    option_order = models.JSONField(default=dict, blank=True)

    class Meta(TenantLearningModel.Meta):
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("quiz", "user", "request_id"),
                name="unique_quiz_attempt_request_per_user",
            )
        ]


class LessonCompletion(TenantLearningModel):
    """Server-owned proof that one enrolled learner finished one lesson."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="completions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_completions",
    )

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "user"), name="unique_lesson_completion_per_user"
            )
        ]


class LearningEvent(TenantLearningModel):
    """One deduplicated, client-sourced learning playback event."""

    KIND_CHOICES = (
        ("position", "Posição"),
        ("complete", "Conclusão"),
        ("pause", "Pausa"),
    )

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_events",
    )
    client_event_id = models.UUIDField()
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    position_seconds = models.PositiveIntegerField()
    active_seconds = models.PositiveIntegerField(default=0)
    user_initiated = models.BooleanField(default=True)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("user", "client_event_id"),
                name="unique_learning_event_per_user",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "lesson", "user"), name="learning_event_idx"
            ),
        ]


class LessonProgress(TenantLearningModel):
    """Server-consolidated per-learner playback state for one lesson."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="progress_records"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
    )
    last_position_seconds = models.PositiveIntegerField(default=0)
    total_active_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "user"), name="unique_lesson_progress_per_user"
            )
        ]


class LessonFavorite(TenantLearningModel):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="favorites"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_favorites",
    )
    active = models.BooleanField(default=True)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "user"), name="unique_lesson_favorite_per_user"
            )
        ]


class PrivateNote(TenantLearningModel):
    """One private learner note bound to a lesson, exportable by the owner."""

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_notes",
    )
    body = models.TextField(max_length=5000)


class ContentRecommendation(TenantLearningModel):
    """One clinical attribution of published content to a patient or cohort."""

    STATUS_CHOICES = (
        ("active", "Ativa"),
        ("retired", "Retirada"),
    )

    content = models.ForeignKey(
        Content, on_delete=models.CASCADE, related_name="recommendations"
    )
    recommended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="content_recommendations_issued",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="content_recommendations",
        blank=True,
        null=True,
    )
    cohort = models.ForeignKey(
        Cohort,
        on_delete=models.CASCADE,
        related_name="content_recommendations",
        blank=True,
        null=True,
    )
    objective = models.CharField(max_length=255)
    priority = models.CharField(max_length=16, default="normal")
    context = models.TextField(max_length=1000, blank=True)
    valid_until = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    retired_reason = models.CharField(max_length=255, blank=True)
    retired_at = models.DateTimeField(blank=True, null=True)
    credential_snapshot = models.JSONField(default=dict, blank=True)
    credential_digest = models.CharField(max_length=64, blank=True)

    class Meta(TenantLearningModel.Meta):
        indexes = [
            models.Index(
                fields=("clinic", "content", "status"),
                name="recommendation_state_idx",
            ),
        ]


class ContentNotification(TenantLearningModel):
    """One in-product alert about a recommendation or content change."""

    KIND_CHOICES = (
        ("recommendation_active", "Recomendação atribuída"),
        ("recommendation_retired", "Recomendação retirada"),
        ("content_removed", "Conteúdo removido"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="content_notifications",
    )
    notification_kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    recommendation = models.ForeignKey(
        ContentRecommendation,
        on_delete=models.CASCADE,
        related_name="notifications",
        blank=True,
        null=True,
    )
    body = models.CharField(max_length=500)

    class Meta(TenantLearningModel.Meta):
        indexes = [
            models.Index(
                fields=("clinic", "recipient", "created_at"),
                name="content_notification_idx",
            ),
        ]


class Certificate(TenantLearningModel):
    """One verifiable, revocable certificate for one completed course."""

    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="certificates"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_certificates",
    )
    public_code = models.CharField(max_length=43, unique=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revocation_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantLearningModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=("course", "user"),
                condition=models.Q(revoked_at__isnull=True),
                name="unique_active_certificate_per_course",
            )
        ]


class ContentReport(TenantLearningModel):
    """One patient-submitted report against published content, with resolution."""

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        RESOLVED = "resolved", "Resolvido"
        DISMISSED = "dismissed", "Descartado"

    content = models.ForeignKey(
        Content, on_delete=models.CASCADE, related_name="reports"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="content_reports",
    )
    reason = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    resolution_note = models.TextField(max_length=2000, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="content_reports_resolved",
    )
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta(TenantLearningModel.Meta):
        indexes = [
            models.Index(
                fields=("clinic", "content", "status"),
                name="content_report_state_idx",
            ),
        ]
