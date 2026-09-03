"""HTTP views for the editorial content and curation domains."""

from __future__ import annotations

import difflib
import html
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from clinics.policies import has_active_clinic_role
from clinics.services import (
    ClinicConfiguration,
    authorized_active_clinic,
)
from core.services import current_correlation_id
from people.selectors import patient_profiles_for_clinic

from .forms import (
    ContentRecommendForm,
    ContentSearchForm,
    EditorialApprovalForm,
    EditorialCommentForm,
    EditorialContentForm,
    EditorialMediaForm,
    EditorialMetadataForm,
    EditorialRollbackForm,
    EditorialVersionForm,
    blocks_body,
)
from .models import Content, ContentReport
from .selectors import (
    current_version_body,
    editorial_comments,
    editorial_content_by_id,
    editorial_contents,
    editorial_version,
    editorial_versions,
    notifications_for_user,
    published_content_by_id,
    published_content_by_slug,
)
from .services import (
    append_editorial_comment,
    approve_content_version,
    archive_content,
    attach_media,
    create_content_version,
    publish_content_version,
    recommend_content,
    recommendations_for_patient,
    resolve_content_report,
    rollback_content,
    search_published_content,
    start_content,
    submit_for_review,
    update_content_metadata,
)

_PAGE_SIZE = 10


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError:
        return uuid4()


def _clinic_timezone_name(clinic_id: UUID) -> str:
    """Return the tenant's configured IANA timezone (Django zone fallback)."""
    configuration = ClinicConfiguration.objects.for_clinic(clinic_id).first()
    name = configuration.timezone_name if configuration is not None else ""
    if name:
        return name
    return timezone.get_current_timezone_name()


def _scheduled_for_utc(clinic_id: UUID, value: datetime | None) -> datetime | None:
    """Interpret the posted wall time in the clinic zone and convert to UTC."""
    if value is None:
        return None
    wall_time = value.replace(tzinfo=None, fold=0)
    local_zone = ZoneInfo(_clinic_timezone_name(clinic_id))
    return wall_time.replace(tzinfo=local_zone).astimezone(UTC)


def _clinic_and_actor(request: HttpRequest) -> tuple[UUID, AbstractBaseUser]:
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk), actor


def _patient_choices(clinic_id: UUID) -> list[tuple[str, str]]:
    return [
        (str(profile.user_id), profile.full_name)
        for profile in patient_profiles_for_clinic(clinic_id=clinic_id)
    ]


def _editorial_actor(request: HttpRequest) -> tuple[UUID, AbstractBaseUser]:
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    return clinic_id, actor


def _editorial_content_or_404(clinic_id: UUID, content_id: UUID) -> Content:
    content = editorial_content_by_id(clinic_id=clinic_id, content_id=content_id)
    if content is None:
        raise Http404
    return content


def _editorial_redirect(content_id: UUID) -> HttpResponseRedirect:
    return HttpResponseRedirect(
        reverse("content_editorial_detail", kwargs={"content_id": content_id})
    )


def _form_errors(request: HttpRequest, form: object) -> None:
    errors = getattr(form, "errors", {})
    for field_errors in errors.values():
        for error in field_errors:
            messages.error(request, error)


def _render_diff(before: str, after: str) -> str:
    rendered: list[str] = []
    for line in difflib.ndiff(before.splitlines(), after.splitlines()):
        value = html.escape(line[2:])
        if line.startswith("- "):
            rendered.append(f'<del class="diff-delete">{value}</del>')
        elif line.startswith("+ "):
            rendered.append(f'<ins class="diff-insert">{value}</ins>')
        elif line.startswith("  "):
            rendered.append(f"<span>{value}</span>")
    return "\n".join(rendered)


@login_required
@require_GET
def editorial_index(request: HttpRequest) -> HttpResponse:
    clinic_id, _actor = _editorial_actor(request)
    return TemplateResponse(
        request,
        "content/editorial_index.html",
        {
            "contents": editorial_contents(clinic_id=clinic_id),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
def editorial_create(request: HttpRequest) -> HttpResponse:
    clinic_id, actor = _editorial_actor(request)
    form = EditorialContentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            content = start_content(
                clinic_id=clinic_id,
                actor=actor,
                slug=form.cleaned_data["slug"],
                title=form.cleaned_data["title"],
                kind=form.cleaned_data["kind"],
                body=blocks_body(form.cleaned_data),
                language_code=form.cleaned_data["language_code"],
                audience=form.cleaned_data["audience"],
                categories=form.comma_list("categories"),
                tags=form.comma_list("tags"),
                contraindications=form.cleaned_data["contraindications"],
                source_reference=form.cleaned_data["source_reference"],
                valid_until=form.cleaned_data["valid_until"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Conteúdo criado como rascunho.")
            return _editorial_redirect(content.pk)
    return TemplateResponse(
        request,
        "content/editorial_create.html",
        {"form": form, "layout_template": "layouts/vertical.html"},
    )


@login_required
@require_GET
def editorial_detail(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, _actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    versions = editorial_versions(clinic_id=clinic_id, content_id=content.pk)
    current = next(
        (version for version in versions if version.version == content.current_version),
        None,
    )
    comments = (
        editorial_comments(clinic_id=clinic_id, content_version_id=current.pk)
        if current is not None
        else []
    )
    return TemplateResponse(
        request,
        "content/editorial_detail.html",
        {
            "content": content,
            "versions": versions,
            "current": current,
            "comments": comments,
            "version_form": EditorialVersionForm(
                initial={"body": current.body if current is not None else ""}
            ),
            "comment_form": EditorialCommentForm(),
            "approval_form": EditorialApprovalForm(),
            "rollback_form": EditorialRollbackForm(),
            "metadata_form": EditorialMetadataForm(
                initial={
                    "contraindications": content.contraindications,
                    "source_reference": content.source_reference,
                    "valid_until": content.valid_until,
                }
            ),
            "media_form": EditorialMediaForm(),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_GET
def editorial_preview(
    request: HttpRequest, content_id: UUID, version: int
) -> HttpResponse:
    clinic_id, _actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    selected = editorial_version(
        clinic_id=clinic_id, content_id=content.pk, version=version
    )
    if selected is None:
        raise Http404
    return TemplateResponse(
        request,
        "content/editorial_preview.html",
        {
            "content": content,
            "version": selected,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_GET
def editorial_compare(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, _actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    try:
        before_number = int(request.GET.get("from", ""))
        after_number = int(request.GET.get("to", ""))
    except ValueError as exc:
        raise Http404 from exc
    before = editorial_version(
        clinic_id=clinic_id, content_id=content.pk, version=before_number
    )
    after = editorial_version(
        clinic_id=clinic_id, content_id=content.pk, version=after_number
    )
    if before is None or after is None:
        raise Http404
    return TemplateResponse(
        request,
        "content/editorial_compare.html",
        {
            "content": content,
            "before": before,
            "after": after,
            "comparison": _render_diff(before.body, after.body),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def editorial_version_create(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    form = EditorialVersionForm(request.POST)
    if form.is_valid():
        try:
            create_content_version(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content.pk,
                body=blocks_body(form.cleaned_data),
                scheduled_for=_scheduled_for_utc(
                    clinic_id, form.cleaned_data["scheduled_for"]
                ),
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Nova versão criada.")
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_metadata_update(request: HttpRequest, content_id: UUID) -> HttpResponse:
    """Update clinical metadata of one editorial content item (admins only)."""
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    form = EditorialMetadataForm(request.POST)
    if form.is_valid():
        try:
            update_content_metadata(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content.pk,
                contraindications=form.cleaned_data["contraindications"],
                source_reference=form.cleaned_data["source_reference"],
                valid_until=form.cleaned_data["valid_until"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Metadados atualizados.")
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_comment(
    request: HttpRequest, content_id: UUID, version: int
) -> HttpResponse:
    clinic_id, actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    form = EditorialCommentForm(request.POST)
    if form.is_valid():
        try:
            append_editorial_comment(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content.pk,
                version=version,
                body=form.cleaned_data["body"],
                request_id=_request_uuid(),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Comentário adicionado ao histórico.")
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


def _editorial_action_context(
    request: HttpRequest, content_id: UUID
) -> tuple[UUID, AbstractBaseUser, Content]:
    clinic_id, actor = _editorial_actor(request)
    content = _editorial_content_or_404(clinic_id, content_id)
    return clinic_id, actor, content


@login_required
@require_POST
def editorial_submit(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    try:
        submit_for_review(
            clinic_id=clinic_id,
            actor=actor,
            content_id=content_id,
            request_id=_request_uuid(),
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_approve(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    form = EditorialApprovalForm(request.POST)
    if form.is_valid():
        try:
            approve_content_version(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content_id,
                opinion=form.cleaned_data["opinion"],
                review_valid_days=form.cleaned_data["review_valid_days"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_rollback(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    form = EditorialRollbackForm(request.POST)
    if form.is_valid():
        try:
            rollback_content(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content_id,
                target_version=form.cleaned_data["target_version"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_archive(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    try:
        archive_content(
            clinic_id=clinic_id,
            actor=actor,
            content_id=content_id,
            request_id=_request_uuid(),
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    return _editorial_redirect(content.pk)


@login_required
@require_POST
def editorial_media(request: HttpRequest, content_id: UUID) -> HttpResponse:
    clinic_id, actor, content = _editorial_action_context(request, content_id)
    form = EditorialMediaForm(request.POST, request.FILES)
    if form.is_valid():
        uploaded = form.cleaned_data["file"]
        try:
            attach_media(
                clinic_id=clinic_id,
                actor=actor,
                content_id=content_id,
                uploaded=uploaded,
                content_type=uploaded.content_type or "",
                original_name=uploaded.name,
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
    else:
        _form_errors(request, form)
    return _editorial_redirect(content.pk)


@login_required
@require_GET
def library_home(request: HttpRequest) -> HttpResponse:
    """Render the tenant's published content library, searchable and paged."""
    clinic_id, _actor = _clinic_and_actor(request)
    form = ContentSearchForm(request.GET or None)
    query = ""
    category = ""
    if form.is_valid():
        query = form.cleaned_data.get("query") or ""
        category = form.cleaned_data.get("category") or ""
    results = search_published_content(
        clinic_id=clinic_id,
        query=query,
        language_code="pt-BR",
        audience="patient",
        category=category,
    )
    paginator = Paginator(results, _PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page") or "1")
    return TemplateResponse(
        request,
        "content/library.html",
        {
            "form": form,
            "page_obj": page,
            "results": list(page.object_list),
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_GET
def content_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Render one published content item; editors see the recommend form."""
    clinic_id, actor = _clinic_and_actor(request)
    content = published_content_by_slug(clinic_id=clinic_id, slug=slug)
    if content is None:
        raise Http404
    body = current_version_body(clinic_id=clinic_id, content=content)
    can_recommend = has_active_clinic_role(
        clinic_id=clinic_id,
        user_id=actor.pk,
        role="therapist",
        on_date=timezone.localdate(),
    )
    recommend_form = None
    if can_recommend:
        recommend_form = ContentRecommendForm(
            patient_choices=_patient_choices(clinic_id)
        )
    return TemplateResponse(
        request,
        "content/detail.html",
        {
            "content": content,
            "body": body,
            "recommend_form": recommend_form,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_GET
def recommendation_list(request: HttpRequest) -> HttpResponse:
    """Render the requesting patient's own active recommendations."""
    clinic_id, actor = _clinic_and_actor(request)
    listing = recommendations_for_patient(clinic_id=clinic_id, user=actor)
    return TemplateResponse(
        request,
        "content/recommendations.html",
        {
            "recommendations": listing,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_GET
def notification_list(request: HttpRequest) -> HttpResponse:
    """Render the requesting user's own in-product notifications."""
    clinic_id, actor = _clinic_and_actor(request)
    notifications = notifications_for_user(clinic_id=clinic_id, user_id=actor.pk)
    return TemplateResponse(
        request,
        "content/notifications.html",
        {
            "notifications": notifications,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_publish(request: HttpRequest, content_id: UUID) -> HttpResponse:
    """Publish an approved content version (professional action)."""
    clinic_id, actor = _clinic_and_actor(request)
    try:
        content = publish_content_version(
            clinic_id=clinic_id,
            actor=actor,
            content_id=content_id,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("content_library"))
    messages.success(request, "Conteúdo publicado.")
    return HttpResponseRedirect(
        reverse("content_detail", kwargs={"slug": content.slug})
    )


@login_required
@require_POST
def content_recommend(request: HttpRequest, content_id: UUID) -> HttpResponse:
    """Attribute published content to a patient (professional action)."""
    clinic_id, actor = _clinic_and_actor(request)
    content = published_content_by_id(clinic_id=clinic_id, content_id=content_id)
    if content is None:
        raise Http404
    recommend_form = ContentRecommendForm(
        request.POST, patient_choices=_patient_choices(clinic_id)
    )
    if not recommend_form.is_valid():
        for field_errors in recommend_form.errors.values():
            for error in field_errors:
                messages.error(request, str(error))
        return HttpResponseRedirect(
            reverse("content_detail", kwargs={"slug": content.slug})
        )
    try:
        recommend_content(
            clinic_id=clinic_id,
            actor=actor,
            content_id=content_id,
            patient_id=UUID(recommend_form.cleaned_data["patient"]),
            cohort_id=None,
            objective=recommend_form.cleaned_data["objective"],
            priority=recommend_form.cleaned_data["priority"],
            context=recommend_form.cleaned_data["context"] or "",
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(
            reverse("content_detail", kwargs={"slug": content.slug})
        )
    messages.success(request, "Recomendação atribuída.")
    return HttpResponseRedirect(
        reverse("content_detail", kwargs={"slug": content.slug})
    )


@login_required
@require_GET
def content_reports(request: HttpRequest) -> HttpResponse:
    """Render the tenant's open content reports for clinic administrators."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    reports = list(
        ContentReport.infrastructure_objects.filter(
            clinic_id=clinic_id, status=ContentReport.Status.OPEN
        )
        .select_related("content", "reporter")
        .order_by("-created_at")
    )
    return TemplateResponse(
        request,
        "content/reports.html",
        {
            "reports": reports,
            "layout_template": "layouts/vertical.html",
        },
    )


@login_required
@require_POST
def content_report_resolve(request: HttpRequest, report_id: UUID) -> HttpResponse:
    """Resolve one content report with a documented decision (admin only)."""
    clinic_id, actor = _clinic_and_actor(request)
    authorized_active_clinic(clinic_id=clinic_id, actor=actor, action="clinic.manage")
    resolution = (request.POST.get("resolution") or "").strip()
    note = (request.POST.get("note") or "").strip()
    try:
        resolve_content_report(
            clinic_id=clinic_id,
            actor=actor,
            report_id=report_id,
            resolution=resolution,
            note=note,
            request_id=_request_uuid(),
        )
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc) or "Não foi possível resolver a denúncia.")
    else:
        messages.success(request, "Denúncia resolvida.")
    return redirect("content_reports")
