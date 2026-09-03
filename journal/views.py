"""HTTP views for the patient emotional journal and calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.services import current_correlation_id
from people.selectors import patient_profile_for_user

from .checkin_forms import DailyCheckInForm
from .forms import JournalEntryForm, JournalFilterForm
from .models import (
    CheckInQuestionnaire,
    DailyCheckIn,
    JournalAccessRequest,
    JournalEntry,
)
from .selectors import (
    patient_journal_calendar_data,
    patient_journal_entries,
    patient_pending_access_requests,
)
from .services import (
    create_journal_entry,
    request_journal_entry_access,
    respond_journal_entry_access_request,
    revoke_journal_entry_sharing,
    save_draft_daily_checkin,
    set_journal_entry_visibility,
    submit_daily_checkin,
    update_journal_entry,
)

_PAGE_SIZE = 10


def _request_uuid() -> UUID:
    try:
        return UUID(current_correlation_id())
    except ValueError:
        return uuid4()


def _clinic_and_actor(request: HttpRequest) -> tuple[UUID, AbstractBaseUser]:
    actor = request.user
    if not isinstance(actor, AbstractBaseUser):
        raise PermissionDenied
    clinic = getattr(request, "clinic", None)
    if clinic is None:
        raise PermissionDenied
    return cast(UUID, clinic.pk), actor


@login_required
@require_GET
def journal_list(request: HttpRequest) -> HttpResponse:
    """Render the patient's emotional diary history and calendar."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    filter_form = JournalFilterForm(request.GET or None)
    period = "30d"
    emotion = ""
    mood_int: int | None = None

    if filter_form.is_valid():
        period = filter_form.cleaned_data.get("period") or "30d"
        emotion = filter_form.cleaned_data.get("emotion") or ""
        mood_str = filter_form.cleaned_data.get("mood") or ""
        if mood_str.isdigit():
            mood_int = int(mood_str)

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
    except ValueError, TypeError:
        year = today.year

    try:
        month = int(request.GET.get("month", today.month))
    except ValueError, TypeError:
        month = today.month

    calendar_data = patient_journal_calendar_data(
        clinic_id=clinic_id,
        actor=actor,
        year=year,
        month=month,
    )

    all_entries = patient_journal_entries(
        clinic_id=clinic_id,
        actor=actor,
        period=period,
        emotion=emotion,
        mood=mood_int,
    )

    pending_requests = patient_pending_access_requests(clinic_id=clinic_id, actor=actor)

    paginator = Paginator(all_entries, _PAGE_SIZE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return TemplateResponse(
        request,
        "journal/list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Diário Emocional",
            "calendar_data": calendar_data,
            "filter_form": filter_form,
            "entries": page_obj,
            "total_entries_count": len(all_entries),
            "selected_period": period,
            "selected_emotion": emotion,
            "selected_mood": str(mood_int) if mood_int is not None else "",
            "pending_access_requests": pending_requests,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def journal_create(request: HttpRequest) -> HttpResponse:
    """Create a new emotional diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    form = JournalEntryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_journal_entry(
                clinic_id=clinic_id,
                actor=actor,
                patient_profile_id=profile.pk,
                mood=form.cleaned_data["mood"],
                emotions=form.cleaned_data.get("emotions") or [],
                intensity=form.cleaned_data["intensity"],
                context=form.cleaned_data["context"],
                triggers=form.cleaned_data.get("triggers", ""),
                reactions=form.cleaned_data.get("reactions", ""),
                strategies=form.cleaned_data.get("strategies", ""),
                visibility=form.cleaned_data["visibility"],
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("journal_list"))

    return TemplateResponse(
        request,
        "journal/form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Novo Registro no Diário",
            "form": form,
            "form_id": "journal-entry-form",
            "submit_label": "Salvar registro",
            "is_editing": False,
        },
    )


@login_required
@require_GET
def journal_detail(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Display a single patient-owned diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    entry = (
        JournalEntry.objects.for_clinic(clinic_id)
        .filter(pk=entry_id, patient_profile_id=profile.pk)
        .first()
    )
    if entry is None:
        raise PermissionDenied

    # Active access requests for this entry
    access_requests = (
        JournalAccessRequest.objects.for_clinic(clinic_id)
        .filter(journal_entry_id=entry.pk)
        .select_related("therapist")
        .order_by("-requested_at")
    )

    return TemplateResponse(
        request,
        "journal/detail.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Detalhe do Registro",
            "entry": entry,
            "access_requests": access_requests,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def journal_edit(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Edit an existing patient diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    entry = (
        JournalEntry.objects.for_clinic(clinic_id)
        .filter(pk=entry_id, patient_profile_id=profile.pk)
        .first()
    )
    if entry is None:
        raise PermissionDenied

    initial_data = {
        "mood": entry.mood,
        "emotions": entry.emotions,
        "intensity": entry.intensity,
        "context": entry.context,
        "triggers": entry.triggers,
        "reactions": entry.reactions,
        "strategies": entry.strategies,
        "visibility": entry.visibility,
    }

    form = JournalEntryForm(request.POST or None, initial=initial_data)
    if request.method == "POST" and form.is_valid():
        try:
            update_journal_entry(
                clinic_id=clinic_id,
                actor=actor,
                journal_entry_id=entry.pk,
                mood=form.cleaned_data["mood"],
                emotions=form.cleaned_data.get("emotions") or [],
                intensity=form.cleaned_data["intensity"],
                context=form.cleaned_data["context"],
                triggers=form.cleaned_data.get("triggers", ""),
                reactions=form.cleaned_data.get("reactions", ""),
                strategies=form.cleaned_data.get("strategies", ""),
                request_id=_request_uuid(),
            )
            if form.cleaned_data["visibility"] != entry.visibility:
                set_journal_entry_visibility(
                    clinic_id=clinic_id,
                    actor=actor,
                    journal_entry_id=entry.pk,
                    visibility=form.cleaned_data["visibility"],
                    request_id=_request_uuid(),
                )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("journal_detail", args=[entry.pk]))

    return TemplateResponse(
        request,
        "journal/form.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Editar Registro no Diário",
            "form": form,
            "form_id": "journal-entry-edit-form",
            "submit_label": "Salvar alterações",
            "is_editing": True,
            "entry": entry,
        },
    )


@login_required
@require_POST
def journal_set_visibility(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Update visibility state for a diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    visibility = request.POST.get("visibility", "")
    set_journal_entry_visibility(
        clinic_id=clinic_id,
        actor=actor,
        journal_entry_id=entry_id,
        visibility=visibility,
        request_id=_request_uuid(),
    )
    next_url = request.POST.get("next") or reverse("journal_detail", args=[entry_id])
    return HttpResponseRedirect(next_url)


@login_required
@require_POST
def journal_revoke_sharing_view(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Immediately revoke all sharing on one diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    reason = request.POST.get("reason", "Revogado pelo paciente")
    revoke_journal_entry_sharing(
        clinic_id=clinic_id,
        actor=actor,
        journal_entry_id=entry_id,
        reason=reason,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("journal_detail", args=[entry_id]))


@login_required
@require_POST
def journal_respond_access_request_view(
    request: HttpRequest, access_request_id: UUID
) -> HttpResponse:
    """Patient approves or rejects a therapist's access request."""
    clinic_id, actor = _clinic_and_actor(request)
    decision = request.POST.get("decision", "reject")
    approved = decision == "approve"

    expires_days = request.POST.get("expires_days", "")
    expires_at: datetime | None = None
    if approved and expires_days.isdigit():
        expires_at = timezone.now() + timedelta(days=int(expires_days))

    respond_journal_entry_access_request(
        clinic_id=clinic_id,
        actor=actor,
        access_request_id=access_request_id,
        approved=approved,
        expires_at=expires_at,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("journal_list"))


@login_required
@require_POST
def journal_request_access_view(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    """Therapist requests access to an Amarelo diary record."""
    clinic_id, actor = _clinic_and_actor(request)
    purpose = request.POST.get("purpose", "Acompanhamento e discussão terapêutica")
    expires_days = request.POST.get("expires_days", "30")
    expires_at: datetime | None = None
    if expires_days.isdigit():
        expires_at = timezone.now() + timedelta(days=int(expires_days))

    request_journal_entry_access(
        clinic_id=clinic_id,
        therapist=actor,
        journal_entry_id=entry_id,
        purpose=purpose,
        expires_at=expires_at,
        request_id=_request_uuid(),
    )
    next_url = request.POST.get("next") or reverse("therapist_dashboard")
    return HttpResponseRedirect(next_url)


@login_required
@require_GET
def checkin_list(request: HttpRequest) -> HttpResponse:
    """Render the patient's personal check-in history."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    checkins = (
        DailyCheckIn.objects.for_clinic(clinic_id)
        .filter(patient_profile_id=profile.pk)
        .order_by("-date", "-submitted_at")
    )
    paginator = Paginator(checkins, _PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return TemplateResponse(
        request,
        "journal/checkin_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Histórico de Check-ins",
            "checkins": page_obj,
            "total_checkins_count": checkins.count(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def checkin_today(request: HttpRequest) -> HttpResponse:
    """Render and submit today's configurable daily check-in."""
    clinic_id, actor = _clinic_and_actor(request)
    profile = patient_profile_for_user(clinic_id=clinic_id, user_id=actor.pk)
    if profile is None:
        raise PermissionDenied

    questionnaire = (
        CheckInQuestionnaire.infrastructure_objects.filter(
            clinic_id=clinic_id, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    if questionnaire is None:
        return TemplateResponse(
            request,
            "journal/checkin_unavailable.html",
            {
                "layout_template": "layouts/vertical.html",
                "page_title": "Check-in Diário",
            },
        )

    today = timezone.localdate()
    existing = (
        DailyCheckIn.objects.for_clinic(clinic_id)
        .filter(
            patient_profile_id=profile.pk,
            date=today,
            period="daily",
        )
        .first()
    )

    idempotency_key = request.POST.get("idempotency_key", "")
    if request.method == "POST" and not idempotency_key:
        # Use the existing submission key or a fresh one for this edition
        idempotency_key = (
            existing.idempotency_key or str(uuid4()) if existing else str(uuid4())
        )

    form = DailyCheckInForm(
        questions=questionnaire.questions,
        data=request.POST or None,
    )

    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "submit")
        answers: dict[str, object] = dict(form.cleaned_data)
        try:
            if action == "save_draft":
                save_draft_daily_checkin(
                    clinic_id=clinic_id,
                    actor=actor,
                    patient_profile_id=profile.pk,
                    answers=answers,
                    period="daily",
                    request_id=_request_uuid(),
                )
                return HttpResponseRedirect(reverse("checkin_today"))
            submit_daily_checkin(
                clinic_id=clinic_id,
                actor=actor,
                patient_profile_id=profile.pk,
                answers=answers,
                period="daily",
                idempotency_key=idempotency_key,
                request_id=_request_uuid(),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return HttpResponseRedirect(reverse("checkin_list"))

    initial: dict[str, object] = {}
    if existing is not None and not existing.is_draft:
        # Edit within configured window shows prior answers
        initial = {
            key: value
            for key, value in (existing.answers or {}).items()
            if value is not None
        }
    elif existing is not None and existing.is_draft:
        initial = dict(existing.answers or {})

    if request.method == "GET" and initial:
        form = DailyCheckInForm(questions=questionnaire.questions, initial=initial)

    total_answered = sum(
        1
        for field in form
        if field.name in form.data and str(form.data[field.name]).strip() != ""
    )
    progress_pct = int((total_answered / max(len(form.fields), 1)) * 100)

    return TemplateResponse(
        request,
        "journal/checkin_today.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Check-in Diário",
            "form": form,
            "questionnaire": questionnaire,
            "existing_checkin": existing,
            "today_date": today,
            "idempotency_key": idempotency_key,
            "progress_pct": progress_pct,
            "total_questions": len(form.fields),
        },
    )
