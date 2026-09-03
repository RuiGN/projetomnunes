"""HTTP views for the PRD 8.12.2 course authoring surface (slices 1-2)."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_GET, require_POST

from clinics.services import authorized_active_clinic

from .learning_authoring import (
    add_cohort_member,
    add_course_prerequisite,
    create_cohort,
    create_course_module,
    create_lesson,
    create_quiz,
    create_quiz_question,
    publish_quiz,
)
from .learning_selectors import (
    learning_course_by_id,
    learning_course_modules,
    learning_module_lessons,
)
from .models import (
    Cohort,
    Course,
    CourseModule,
    Enrollment,
    Lesson,
    Quiz,
    QuizAttempt,
    QuizQuestion,
)
from .selectors import (
    active_certificate_for_user,
    certificate_by_public_code,
    course_is_completed_for_user,
)
from .services import create_course as _create_course
from .services import enroll_individual as _enroll_individual
from .services import (
    issue_certificate_for_participant,
    quiz_attempt_feedback,
    quiz_questions_for_participant,
    submit_quiz_attempt,
)
from .services import lesson_progress as _lesson_progress
from .services import publish_course as _publish_course
from .services import record_learning_event as _record_learning_event


def _request_uuid() -> UUID:
    try:
        from core.services import current_correlation_id

        return UUID(current_correlation_id())
    except ValueError, TypeError:
        return uuid4()


def _clinic_and_actor(request: HttpRequest) -> tuple[UUID, AbstractBaseUser]:
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk), actor


def _builder_context(
    request: HttpRequest, course_id: UUID
) -> tuple[UUID, AbstractBaseUser, Course]:
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    course = learning_course_by_id(clinic_id=clinic_id, course_id=course_id)
    if course is None:
        from django.http import Http404

        raise Http404
    return clinic_id, actor, course


def _module_or_404(clinic_id: UUID, course: Course, module_id: UUID) -> CourseModule:
    from django.http import Http404

    module = CourseModule.infrastructure_objects.filter(
        clinic_id=clinic_id, pk=module_id, course_id=course.pk
    ).first()
    if module is None:
        raise Http404
    return cast(CourseModule, module)


@login_required
@require_GET
def content_course_authoring_detail(
    request: HttpRequest, course_id: UUID
) -> HttpResponse:
    """Render the tenant course builder with ordered draft modules."""
    clinic_id, actor, course = _builder_context(request, course_id)
    modules = learning_course_modules(clinic_id=clinic_id, course_id=course.pk)
    return TemplateResponse(
        request,
        "content/learning/course_detail.html",
        {
            "course": course,
            "modules": modules,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_course_module_create(request: HttpRequest, course_id: UUID) -> HttpResponse:
    """Create one ordered draft module for a tenant course."""
    clinic_id, actor, course = _builder_context(request, course_id)
    title = (request.POST.get("title") or "").strip()
    try:
        position = int(request.POST.get("position") or 0)
    except ValueError:
        position = 0
    if title:
        try:
            create_course_module(
                clinic_id=clinic_id,
                actor=actor,
                course_id=course.pk,
                title=title,
                position=position,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Módulo criado.")
    else:
        messages.error(request, "Informe o título do módulo.")
    return redirect("content_course_authoring_detail", course_id=course.pk)


@login_required
@require_GET
def content_course_module_detail(
    request: HttpRequest, course_id: UUID, module_id: UUID
) -> HttpResponse:
    """Render one tenant module with ordered lessons."""
    clinic_id, actor, course = _builder_context(request, course_id)
    module = _module_or_404(clinic_id, course, module_id)
    lessons = learning_module_lessons(clinic_id=clinic_id, module_id=module.pk)
    return TemplateResponse(
        request,
        "content/learning/module_detail.html",
        {
            "course": course,
            "module": module,
            "lessons": lessons,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_course_lesson_create(
    request: HttpRequest, course_id: UUID, module_id: UUID
) -> HttpResponse:
    """Create one ordered lesson inside a tenant module."""
    clinic_id, actor, course = _builder_context(request, course_id)
    module = _module_or_404(clinic_id, course, module_id)
    title = (request.POST.get("title") or "").strip()
    try:
        position = int(request.POST.get("position") or 0)
        duration_minutes = int(request.POST.get("duration_minutes") or 0)
    except ValueError:
        position = 0
        duration_minutes = 0
    if title:
        try:
            create_lesson(
                clinic_id=clinic_id,
                actor=actor,
                module_id=module.pk,
                title=title,
                duration_minutes=duration_minutes,
                position=position,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Aula criada.")
    else:
        messages.error(request, "Informe o título da aula.")
    return redirect(
        "content_course_module_detail", course_id=course.pk, module_id=module.pk
    )


@login_required
@require_POST
def content_course_prerequisite_add(
    request: HttpRequest, course_id: UUID
) -> HttpResponse:
    """Add one tenant-local prerequisite edge to a draft course."""
    clinic_id, actor, course = _builder_context(request, course_id)
    raw_id = (request.POST.get("prerequisite_course_id") or "").strip()
    try:
        prerequisite_course_id = UUID(raw_id)
    except ValueError:
        messages.error(request, "Informe um curso de pré-requisito válido.")
        return redirect("content_course_authoring_detail", course_id=course.pk)
    try:
        add_course_prerequisite(
            clinic_id=clinic_id,
            actor=actor,
            course_id=course.pk,
            prerequisite_course_id=prerequisite_course_id,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Pré-requisito vinculado.")
    return redirect("content_course_authoring_detail", course_id=course.pk)


@login_required
@require_POST
def content_course_publish(request: HttpRequest, course_id: UUID) -> HttpResponse:
    """Publish one complete tenant curriculum atomically."""
    clinic_id, actor, course = _builder_context(request, course_id)
    try:
        _publish_course(
            clinic_id=clinic_id,
            actor=actor,
            course_id=course.pk,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Curso publicado.")
    return redirect("content_course_authoring_detail", course_id=course.pk)


@login_required
@require_POST
def content_cohort_create(request: HttpRequest) -> HttpResponse:
    """Create one tenant-unique cohort."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    name = (request.POST.get("name") or "").strip()
    if name:
        try:
            cohort = create_cohort(
                clinic_id=clinic_id,
                actor=actor,
                name=name,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("content_learning_authoring_index")
        else:
            messages.success(request, "Coorte criada.")
            return redirect("content_cohort_detail", cohort_id=cohort.pk)
    messages.error(request, "Informe o nome da coorte.")
    return redirect("content_learning_authoring_index")


@login_required
@require_GET
def content_cohort_detail(request: HttpRequest, cohort_id: UUID) -> HttpResponse:
    """Render one tenant cohort with its members."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    cohort = Cohort.infrastructure_objects.filter(
        clinic_id=clinic_id, pk=cohort_id
    ).first()
    if cohort is None:
        from django.http import Http404

        raise Http404
    members = list(cohort.members.select_related("user").order_by("created_at"))
    return TemplateResponse(
        request,
        "content/learning/cohort_detail.html",
        {
            "cohort": cohort,
            "members": members,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_cohort_member_add(request: HttpRequest, cohort_id: UUID) -> HttpResponse:
    """Add one user to a tenant cohort."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    cohort = Cohort.infrastructure_objects.filter(
        clinic_id=clinic_id, pk=cohort_id
    ).first()
    if cohort is None:
        from django.http import Http404

        raise Http404
    raw_user = (request.POST.get("user_id") or "").strip()
    try:
        user_id = UUID(raw_user)
    except ValueError:
        messages.error(request, "Informe um usuário válido.")
        return redirect("content_cohort_detail", cohort_id=cohort.pk)
    try:
        add_cohort_member(
            clinic_id=clinic_id,
            actor=actor,
            cohort_id=cohort.pk,
            user_id=user_id,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Membro adicionado.")
    return redirect("content_cohort_detail", cohort_id=cohort.pk)


@login_required
@require_GET
def content_learning_authoring_index(request: HttpRequest) -> HttpResponse:
    """Admin entry point listing tenant courses, paths, cohorts and quizzes."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    courses = list(
        Course.infrastructure_objects.filter(clinic_id=clinic_id).order_by(
            "title", "id"
        )
    )
    cohorts = list(
        Cohort.infrastructure_objects.filter(clinic_id=clinic_id).order_by("name")
    )
    quizzes = list(
        Quiz.infrastructure_objects.filter(clinic_id=clinic_id).order_by("title")
    )
    return TemplateResponse(
        request,
        "content/learning/index.html",
        {
            "courses": courses,
            "cohorts": cohorts,
            "quizzes": quizzes,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_quiz_create(request: HttpRequest, course_id: UUID) -> HttpResponse:
    """Create one explicit draft educational quiz."""
    clinic_id, actor, course = _builder_context(request, course_id)
    slug = (request.POST.get("slug") or "").strip()
    title = (request.POST.get("title") or "").strip()
    try:
        minimum_grade = int(request.POST.get("minimum_grade") or 70)
        max_attempts = int(request.POST.get("max_attempts") or 3)
    except ValueError:
        minimum_grade = 0
        max_attempts = 0
    shuffle = request.POST.get("shuffle_questions") == "on"
    if slug and title:
        try:
            quiz = create_quiz(
                clinic_id=clinic_id,
                actor=actor,
                course_id=course.pk,
                slug=slug,
                title=title,
                minimum_grade=minimum_grade,
                max_attempts=max_attempts,
                shuffle_questions=shuffle,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("content_course_authoring_detail", course_id=course.pk)
        else:
            messages.success(request, "Questionário criado.")
            return redirect("content_quiz_detail", quiz_id=quiz.pk)
    messages.error(request, "Informe slug e título do questionário.")
    return redirect("content_course_authoring_detail", course_id=course.pk)


@login_required
@require_GET
def content_quiz_detail(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Render one tenant quiz with ordered questions."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    quiz = (
        Quiz.infrastructure_objects.filter(clinic_id=clinic_id, pk=quiz_id)
        .select_related("course")
        .first()
    )
    if quiz is None:
        from django.http import Http404

        raise Http404
    questions = list(
        QuizQuestion.infrastructure_objects.filter(quiz_id=quiz.pk).order_by(
            "position", "id"
        )
    )
    return TemplateResponse(
        request,
        "content/learning/quiz_detail.html",
        {
            "quiz": quiz,
            "course": quiz.course,
            "questions": questions,
            "disclaimer": (
                "Avaliação educacional — não produz diagnóstico "
                "nem decisão clínica automática"
            ),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_quiz_question_create(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Create one ordered question for a tenant quiz."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    quiz = (
        Quiz.infrastructure_objects.select_related("course")
        .filter(clinic_id=clinic_id, pk=quiz_id)
        .first()
    )
    if quiz is None:
        from django.http import Http404

        raise Http404
    prompt = (request.POST.get("prompt") or "").strip()
    options = {
        key: (request.POST.get(f"option_{key}") or "") for key in ("a", "b", "c", "d")
    }
    correct_key = (request.POST.get("correct_key") or "").strip()
    explanation = (request.POST.get("explanation") or "").strip()
    try:
        position = int(request.POST.get("position") or 0)
    except ValueError:
        position = 0
    if prompt:
        try:
            create_quiz_question(
                clinic_id=clinic_id,
                actor=actor,
                quiz_id=quiz.pk,
                prompt=prompt,
                options=options,
                correct_key=correct_key,
                explanation=explanation,
                position=position,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Questão criada.")
    else:
        messages.error(request, "Informe o enunciado da questão.")
    return redirect("content_quiz_detail", quiz_id=quiz.pk)


@login_required
@require_POST
def content_quiz_publish(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Publish one tenant quiz after readiness validation."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    quiz = (
        Quiz.infrastructure_objects.select_related("course")
        .filter(clinic_id=clinic_id, pk=quiz_id)
        .first()
    )
    if quiz is None:
        from django.http import Http404

        raise Http404
    try:
        publish_quiz(
            clinic_id=clinic_id,
            actor=actor,
            quiz_id=quiz.pk,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Questionário publicado.")
    return redirect("content_quiz_detail", quiz_id=quiz.pk)


@login_required
@require_POST
def content_course_create(request: HttpRequest) -> HttpResponse:
    """Create one tenant draft course with an authorized instructor."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    slug = (request.POST.get("slug") or "").strip()
    title = (request.POST.get("title") or "").strip()
    duration_raw = request.POST.get("duration_minutes") or ""
    instructor_raw = request.POST.get("instructor_id") or ""
    try:
        duration_minutes = int(duration_raw)
    except TypeError, ValueError:
        duration_minutes = 0
    try:
        instructor_id = UUID(instructor_raw)
    except TypeError, ValueError:
        instructor_id = None
    if slug and title and duration_minutes > 0 and instructor_id is not None:
        try:
            course = _create_course(
                clinic_id=clinic_id,
                actor=actor,
                slug=slug,
                title=title,
                duration_minutes=duration_minutes,
                instructor_id=instructor_id,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(
                request, str(exc) or "Não foi possível criar o curso com estes dados."
            )
        else:
            messages.success(request, "Curso criado.")
            return redirect("content_course_authoring_detail", course_id=course.pk)
    else:
        messages.error(
            request,
            "Informe slug, título, duração e instrutor válidos para o curso.",
        )
    return redirect("content_learning_authoring_index")


@login_required
@require_POST
def content_course_enroll(request: HttpRequest, course_id: UUID) -> HttpResponse:
    """Enroll the acting tenant member in one available course (participant path)."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        from django.http import Http404

        raise Http404
    try:
        idempotency_key = UUID(request.POST.get("idempotency_key") or "")
    except TypeError, ValueError:
        idempotency_key = uuid4()
    try:
        _enroll_individual(
            clinic_id=clinic_id,
            user=actor,
            course_id=course.pk,
            plan_codes=set(),
            invitation_id=None,
            idempotency_key=idempotency_key,
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Matrícula realizada.")
    return redirect("content_library")


def _enrolled_lesson_or_404(
    clinic_id: UUID, course_id: UUID, lesson_id: UUID
) -> tuple[Course, Lesson]:
    """Resolve one tenant lesson under a tenant course; 404 when unrelated."""
    from django.http import Http404

    from .models import Lesson

    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        raise Http404
    lesson = Lesson.infrastructure_objects.filter(
        pk=lesson_id, clinic_id=clinic_id, module__course_id=course.pk
    ).first()
    if lesson is None:
        raise Http404
    return course, lesson


@login_required
@require_GET
def content_lesson_player(
    request: HttpRequest, course_id: UUID, lesson_id: UUID
) -> HttpResponse:
    """Render one enrolled lesson page with the accessible player contract."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    course, lesson = _enrolled_lesson_or_404(clinic_id, course_id, lesson_id)
    enrolled = Enrollment.infrastructure_objects.filter(
        clinic_id=clinic_id,
        course_id=course.pk,
        user_id=actor.pk,
        ended_at__isnull=True,
    ).exists()
    if not enrolled:
        messages.error(request, "Você ainda não está matriculado neste curso.")
        return redirect("content_library")
    progress = _lesson_progress(clinic_id=clinic_id, user=actor, lesson_id=lesson.pk)
    return TemplateResponse(
        request,
        "content/learning/lesson_page.html",
        {
            "course": course,
            "lesson": lesson,
            "player": {
                "title": lesson.title,
                "resume_seconds": progress.last_position_seconds or 0,
                "duration_minutes": lesson.duration_minutes,
                "transcript": lesson.transcript,
                "captions": lesson.captions,
            },
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_lesson_event(
    request: HttpRequest, course_id: UUID, lesson_id: UUID
) -> HttpResponse:
    """Record one deduplicated playback event for an enrolled learner."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    course, lesson = _enrolled_lesson_or_404(clinic_id, course_id, lesson_id)
    try:
        client_event_id = UUID(request.POST.get("client_event_id") or "")
    except TypeError, ValueError:
        client_event_id = uuid4()
    kind = (request.POST.get("kind") or "position").strip() or "position"
    try:
        position_seconds = int(request.POST.get("position_seconds") or 0)
        active_seconds = int(request.POST.get("active_seconds") or 0)
    except TypeError, ValueError:
        position_seconds = 0
        active_seconds = 0
    user_initiated = (request.POST.get("user_initiated") or "true") == "true"
    try:
        _record_learning_event(
            clinic_id=clinic_id,
            user=actor,
            lesson_id=lesson.pk,
            client_event_id=client_event_id,
            kind=kind,
            position_seconds=max(position_seconds, 0),
            active_seconds=max(active_seconds, 0),
            user_initiated=user_initiated,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc) or "Evento de aprendizagem rejeitado.")
    else:
        messages.success(request, "Progresso salvo.")
    return redirect("content_lesson_player", course_id=course.pk, lesson_id=lesson.pk)


@login_required
@require_GET
def content_quiz_participate(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Render the participant-safe quiz form without answer keys."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    quiz = (
        Quiz.infrastructure_objects.filter(pk=quiz_id, clinic_id=clinic_id)
        .select_related("course")
        .first()
    )
    if quiz is None:
        from django.http import Http404

        raise Http404
    request_id = uuid4()
    seed = request_id.int & ((1 << 63) - 1)
    try:
        questions = quiz_questions_for_participant(
            clinic_id=clinic_id, user=actor, quiz_id=quiz.pk, seed=seed
        )
    except PermissionDenied as exc:
        from django.http import Http404

        raise Http404 from exc
    return TemplateResponse(
        request,
        "content/learning/quiz_participate.html",
        {
            "quiz": quiz,
            "course": quiz.course,
            "questions": questions,
            "request_id": str(request_id),
            "shuffle_seed": seed,
            "disclaimer": (
                "Avaliação educacional — não produz diagnóstico "
                "nem decisão clínica automática"
            ),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_quiz_submit(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Grade one idempotent educational attempt for the acting participant."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    quiz = Quiz.infrastructure_objects.filter(pk=quiz_id, clinic_id=clinic_id).first()
    if quiz is None:
        from django.http import Http404

        raise Http404
    try:
        request_id = UUID(request.POST.get("request_id") or "")
    except TypeError, ValueError:
        request_id = uuid4()
    try:
        shuffle_seed = int(request.POST.get("shuffle_seed") or 0)
    except TypeError, ValueError:
        shuffle_seed = 0
    answers: dict[str, str] = {}
    for key, value in request.POST.items():
        if key.startswith("answer_"):
            answers[key[len("answer_") :]] = str(value)
    try:
        attempt = submit_quiz_attempt(
            clinic_id=clinic_id,
            user=actor,
            quiz_id=quiz.pk,
            answers=answers,
            request_id=request_id,
            shuffle_seed=shuffle_seed,
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc) or "Tentativa rejeitada.")
        return redirect("content_quiz_participate", quiz_id=quiz.pk)
    return redirect("content_quiz_feedback", attempt_id=attempt.pk)


@login_required
@require_GET
def content_quiz_feedback(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    """Render the acting participant's own attempt feedback."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    attempt = (
        QuizAttempt.infrastructure_objects.filter(pk=attempt_id, clinic_id=clinic_id)
        .select_related("quiz")
        .first()
    )
    if attempt is None or attempt.user_id != actor.pk:
        from django.http import Http404

        raise Http404
    feedback = quiz_attempt_feedback(
        clinic_id=clinic_id, user=actor, attempt_id=attempt.pk
    )
    return TemplateResponse(
        request,
        "content/learning/quiz_feedback.html",
        {
            "attempt": attempt,
            "quiz": attempt.quiz,
            "feedback": feedback,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
def content_course_certificate(request: HttpRequest, course_id: UUID) -> HttpResponse:
    """Render the participant's certificate status and issue it on POST."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="course.enroll")
    course = Course.infrastructure_objects.filter(
        pk=course_id, clinic_id=clinic_id
    ).first()
    if course is None:
        from django.http import Http404

        raise Http404
    if request.method == "POST":
        try:
            issue_certificate_for_participant(
                clinic_id=clinic_id,
                user=actor,
                course_id=course.pk,
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(
                request, str(exc) or "Não foi possível emitir o certificado."
            )
        else:
            messages.success(request, "Certificado emitido.")
        return redirect("content_course_certificate", course_id=course.pk)
    certificate = active_certificate_for_user(
        clinic_id=clinic_id, course_id=course.pk, user_id=actor.pk
    )
    completed = course_is_completed_for_user(
        clinic_id=clinic_id, course_id=course.pk, user_id=actor.pk
    )
    return TemplateResponse(
        request,
        "content/learning/certificate.html",
        {
            "course": course,
            "certificate": certificate,
            "completed": completed,
            "layout_template": "layouts/vertical.html",
        },
    )


@require_GET
def content_certificate_verify(request: HttpRequest, public_code: str) -> HttpResponse:
    """Publicly verify one certificate code without exposing personal data."""
    certificate = certificate_by_public_code(public_code)
    if certificate is None:
        from django.http import Http404

        raise Http404
    status = "revoked" if certificate.revoked_at is not None else "valid"
    return TemplateResponse(
        request,
        "content/learning/certificate_verify.html",
        {
            "status": status,
            "course_title": certificate.course.title,
            "layout_template": "layouts/base.html",
        },
    )
