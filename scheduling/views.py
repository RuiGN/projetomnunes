"""HTTP views for the agenda, reminders and asynchronous messaging."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import cast
from uuid import UUID, uuid4

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from clinics.policies import has_active_clinic_role
from clinics.selectors import clinic_operating_hours
from core.services import current_correlation_id
from people.selectors import (
    linked_patients_for_therapist,
    linked_therapists_for_patient,
)

from .forms import (
    AppointmentActionForm,
    AppointmentRequestForm,
    AppointmentRescheduleForm,
    ConversationForm,
    MessageForm,
    ReminderPreferenceForm,
)
from .messaging_services import (
    create_conversation,
    delete_attachment,
    download_attachment,
    mark_conversation_read,
    send_message,
)
from .models import (
    Appointment,
    MessageAttachment,
    Service,
    Unit,
)
from .operating_hours import out_of_hours_response
from .reminder_services import upsert_reminder_preference
from .selectors import (
    appointments_visible_to,
    conversations_for_actor,
    messages_for_conversation,
    reminder_preferences_for_patient,
)
from .services import (
    cancel_appointment,
    complete_appointment,
    confirm_appointment,
    record_no_show,
    request_appointment,
    request_reschedule,
)

NON_EMERGENCY_NOTICE = (
    "Este canal não atende emergências. Em perigo imediato, acione o serviço "
    "de emergência da sua localidade."
)


def _request_uuid() -> UUID:
    try:
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


def _active_service(clinic_id: UUID, service_id: str) -> Service | None:
    try:
        parsed = UUID(service_id)
    except ValueError, TypeError:
        return None
    return (
        Service.objects.for_clinic(clinic_id).filter(pk=parsed, is_active=True).first()
    )


# ---------------------------------------------------------------------------
# Agenda / appointments (8.8.2)
# ---------------------------------------------------------------------------


@login_required
@require_GET
def appointment_list(request: HttpRequest) -> HttpResponse:
    """Render the actor's authorized appointments as a textual agenda."""
    clinic_id, actor = _clinic_and_actor(request)
    status_filter = request.GET.get("status", "")
    appointments = appointments_visible_to(
        clinic_id=clinic_id, actor=actor, status=status_filter
    )
    today = timezone.localdate()
    can_manage = any(
        has_active_clinic_role(
            clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
        )
        for role in ("clinic_admin", "administrative_staff", "therapist")
    )
    return TemplateResponse(
        request,
        "scheduling/appointment_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Agenda",
            "appointments": appointments,
            "selected_status": status_filter,
            "can_manage": can_manage,
            "non_emergency_notice": NON_EMERGENCY_NOTICE,
        },
    )


@login_required
@require_GET
def appointment_calendar(request: HttpRequest) -> HttpResponse:
    """Render a weekly calendar grid plus an equivalent textual list (8.8.1.3)."""
    clinic_id, actor = _clinic_and_actor(request)
    today = timezone.localdate()
    raw_date = request.GET.get("date", "")
    if raw_date:
        try:
            today = date.fromisoformat(raw_date)
        except ValueError:
            today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    days = [week_start + timedelta(days=offset) for offset in range(7)]

    from_at = timezone.make_aware(datetime.combine(days[0], time.min))
    to_at = timezone.make_aware(
        datetime.combine(days[-1] + timedelta(days=1), time.min)
    )
    appointments = appointments_visible_to(
        clinic_id=clinic_id, actor=actor, from_at=from_at, to_at=to_at
    )
    by_day: dict[date, list[Appointment]] = {day: [] for day in days}
    for appointment in appointments:
        local_day = timezone.localtime(appointment.start_at).date()
        if local_day in by_day:
            by_day[local_day].append(appointment)
    week_days = [(day, by_day[day]) for day in days]

    return TemplateResponse(
        request,
        "scheduling/appointment_calendar.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Agenda semanal",
            "days": days,
            "week_days": week_days,
            "appointments": appointments,
            "week_start": week_start,
            "prev_week": (week_start - timedelta(days=7)).isoformat(),
            "next_week": (week_start + timedelta(days=7)).isoformat(),
            "can_manage": any(
                has_active_clinic_role(
                    clinic_id=clinic_id, user_id=actor.pk, role=role, on_date=today
                )
                for role in ("clinic_admin", "administrative_staff", "therapist")
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def appointment_request(request: HttpRequest) -> HttpResponse:
    """Collect and submit a patient's idempotent consultation request."""
    clinic_id, actor = _clinic_and_actor(request)

    service_choices = [
        (str(service.pk), service.name)
        for service in Service.objects.for_clinic(clinic_id).filter(is_active=True)
    ]
    today = timezone.localdate()
    therapist_rows = linked_therapists_for_patient(
        clinic_id=clinic_id, patient_user_id=actor.pk, on_date=today
    )
    professional_choices = [
        (str(row.therapist_id), row.full_name) for row in therapist_rows
    ]
    unit_choices = [
        (str(unit.pk), unit.name)
        for unit in Unit.objects.for_clinic(clinic_id).filter(is_active=True)
    ]

    form = AppointmentRequestForm(
        request.POST or None,
        service_choices=service_choices,
        professional_choices=professional_choices,
        unit_choices=unit_choices,
    )
    if request.method == "POST" and form.is_valid():
        service = _active_service(clinic_id, form.cleaned_data["service"])
        if service is None:
            form.add_error("service", "Selecione um serviço válido.")
        else:
            start_at = form.cleaned_data["start_at"]
            end_at = start_at + timedelta(minutes=service.duration_minutes)
            request_appointment(
                clinic_id=clinic_id,
                actor=actor,
                service_id=service.pk,
                professional_id=UUID(form.cleaned_data["professional"]),
                unit_id=UUID(form.cleaned_data["unit"]),
                start_at=start_at,
                end_at=end_at,
                idempotency_key=f"req:{_request_uuid()}",
                request_id=_request_uuid(),
            )
            return HttpResponseRedirect(reverse("appointment_list"))
    return TemplateResponse(
        request,
        "scheduling/appointment_request.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Solicitar consulta",
            "form": form,
            "submit_label": "Solicitar consulta",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def appointment_reschedule(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    """Propose a new slot for one appointment."""
    clinic_id, actor = _clinic_and_actor(request)
    form = AppointmentRescheduleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        appointment = (
            Appointment.objects.for_clinic(clinic_id).filter(pk=appointment_id).first()
        )
        if appointment is None:
            raise PermissionDenied
        start_at = form.cleaned_data["start_at"]
        end_at = start_at + timedelta(minutes=appointment.service.duration_minutes)
        request_reschedule(
            clinic_id=clinic_id,
            actor=actor,
            appointment_id=appointment_id,
            start_at=start_at,
            end_at=end_at,
            request_id=_request_uuid(),
        )
        return HttpResponseRedirect(reverse("appointment_list"))
    return TemplateResponse(
        request,
        "scheduling/appointment_reschedule.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Remarcar consulta",
            "form": form,
            "submit_label": "Propor novo horário",
        },
    )


@login_required
@require_POST
def appointment_confirm(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    clinic_id, actor = _clinic_and_actor(request)
    confirm_appointment(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("appointment_list"))


@login_required
@require_POST
def appointment_cancel(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    clinic_id, actor = _clinic_and_actor(request)
    form = AppointmentActionForm(request.POST or None)
    reason = form["reason"].value() if "reason" in form.data else ""
    cancel_appointment(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        reason=reason or "",
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("appointment_list"))


@login_required
@require_POST
def appointment_complete(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    clinic_id, actor = _clinic_and_actor(request)
    complete_appointment(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("appointment_list"))


@login_required
@require_POST
def appointment_no_show(request: HttpRequest, appointment_id: UUID) -> HttpResponse:
    clinic_id, actor = _clinic_and_actor(request)
    record_no_show(
        clinic_id=clinic_id,
        actor=actor,
        appointment_id=appointment_id,
        request_id=_request_uuid(),
    )
    return HttpResponseRedirect(reverse("appointment_list"))


# ---------------------------------------------------------------------------
# Reminder preferences (8.8.3)
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def reminder_preferences(request: HttpRequest) -> HttpResponse:
    """Let the patient manage their own reminder preferences."""
    clinic_id, actor = _clinic_and_actor(request)
    if request.method == "POST":
        form = ReminderPreferenceForm(request.POST)
        if form.is_valid():
            upsert_reminder_preference(
                clinic_id=clinic_id,
                actor=actor,
                reminder_type=form.cleaned_data["reminder_type"],
                channel=form.cleaned_data["channel"],
                enabled=form.cleaned_data.get("enabled", False),
                advance_minutes=form.cleaned_data["advance_minutes"],
                silence_start=form.cleaned_data.get("silence_start"),
                silence_end=form.cleaned_data.get("silence_end"),
                timezone_name=form.cleaned_data.get("timezone_name")
                or "America/Sao_Paulo",
                max_daily=form.cleaned_data["max_daily"],
            )
            return HttpResponseRedirect(reverse("reminder_preferences"))
    else:
        form = ReminderPreferenceForm()

    preferences = reminder_preferences_for_patient(clinic_id=clinic_id, actor=actor)
    return TemplateResponse(
        request,
        "scheduling/reminder_preferences.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Preferências de lembrete",
            "form": form,
            "preferences": preferences,
            "submit_label": "Salvar preferência",
        },
    )


# ---------------------------------------------------------------------------
# Asynchronous messaging (8.8.4)
# ---------------------------------------------------------------------------


@login_required
@require_GET
def conversation_list(request: HttpRequest) -> HttpResponse:
    """List the actor's active conversations."""
    clinic_id, actor = _clinic_and_actor(request)
    conversations = conversations_for_actor(clinic_id=clinic_id, actor=actor)
    return TemplateResponse(
        request,
        "scheduling/conversation_list.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Mensagens",
            "conversations": conversations,
            "non_emergency_notice": NON_EMERGENCY_NOTICE,
        },
    )


def _participant_choices(
    clinic_id: UUID, actor: AbstractBaseUser
) -> list[tuple[str, str]]:
    today = timezone.localdate()

    if has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="patient", on_date=today
    ):
        return [
            (str(row.therapist_id), row.full_name)
            for row in linked_therapists_for_patient(
                clinic_id=clinic_id, patient_user_id=actor.pk, on_date=today
            )
        ]
    if has_active_clinic_role(
        clinic_id=clinic_id, user_id=actor.pk, role="therapist", on_date=today
    ):
        return [
            (str(row.user_id), row.full_name)
            for row in linked_patients_for_therapist(
                clinic_id=clinic_id, therapist_id=actor.pk, on_date=today
            )
            if row.user_id is not None
        ]
    return []


@login_required
@require_http_methods(["GET", "POST"])
def conversation_create(request: HttpRequest) -> HttpResponse:
    """Create one typed conversation restricted to bound participants."""
    clinic_id, actor = _clinic_and_actor(request)
    participant_choices = _participant_choices(clinic_id, actor)
    form = ConversationForm(
        request.POST or None, participant_choices=participant_choices
    )
    if request.method == "POST" and form.is_valid():
        conversation = create_conversation(
            clinic_id=clinic_id,
            actor=actor,
            kind=form.cleaned_data["kind"],
            subject=form.cleaned_data.get("subject", ""),
            participant_ids=[
                UUID(value) for value in form.cleaned_data["participant_ids"]
            ],
            request_id=_request_uuid(),
        )
        return HttpResponseRedirect(
            reverse("conversation_detail", args=[conversation.pk])
        )
    return TemplateResponse(
        request,
        "scheduling/conversation_create.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": "Nova conversa",
            "form": form,
            "submit_label": "Iniciar conversa",
            "non_emergency_notice": NON_EMERGENCY_NOTICE,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def conversation_detail(request: HttpRequest, conversation_id: UUID) -> HttpResponse:
    """Show one conversation, send a message and mark it read."""
    clinic_id, actor = _clinic_and_actor(request)
    messages = messages_for_conversation(
        clinic_id=clinic_id, actor=actor, conversation_id=conversation_id
    )
    if not messages and not conversations_for_actor(clinic_id=clinic_id, actor=actor):
        raise PermissionDenied

    form = MessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        send_message(
            clinic_id=clinic_id,
            actor=actor,
            conversation_id=conversation_id,
            body=form.cleaned_data["body"],
            request_id=_request_uuid(),
        )
        return HttpResponseRedirect(
            reverse("conversation_detail", args=[conversation_id])
        )

    mark_conversation_read(
        clinic_id=clinic_id, actor=actor, conversation_id=conversation_id
    )
    conversation = next(
        (
            candidate
            for candidate in conversations_for_actor(clinic_id=clinic_id, actor=actor)
            if candidate.pk == conversation_id
        ),
        None,
    )
    if conversation is None:
        raise PermissionDenied

    paginator = Paginator(messages, 50)
    try:
        page_number = int(request.GET.get("page", "1"))
    except ValueError:
        page_number = 1
    page_obj = paginator.get_page(page_number)

    attachments_by_message: dict[UUID, list[MessageAttachment]] = defaultdict(list)
    for attachment in MessageAttachment.objects.for_clinic(clinic_id).filter(
        message_id__in=[message.pk for message in page_obj.object_list]
    ):
        attachments_by_message[attachment.message_id].append(attachment)
    for message in page_obj.object_list:
        message.attachments_list = attachments_by_message.get(message.pk, [])

    out_of_hours_notice = ""
    operating = clinic_operating_hours(clinic_id=clinic_id)
    if operating is not None:
        out_of_hours_notice = (
            out_of_hours_response(
                weekly_hours=operating.weekly_hours,
                now=timezone.now(),
                tz_name=operating.timezone_name,
                instructions=operating.out_of_hours_instructions,
            )
            or ""
        )

    return TemplateResponse(
        request,
        "scheduling/conversation_detail.html",
        {
            "layout_template": "layouts/vertical.html",
            "page_title": conversation.subject or "Conversa",
            "conversation": conversation,
            "messages": page_obj.object_list,
            "page_obj": page_obj,
            "form": form,
            "submit_label": "Enviar",
            "non_emergency_notice": NON_EMERGENCY_NOTICE,
            "out_of_hours_notice": out_of_hours_notice,
        },
    )


@login_required
@require_GET
def attachment_download(request: HttpRequest, attachment_id: UUID) -> FileResponse:
    """Serve one clean, authorized attachment privately (8.8.5.2)."""
    clinic_id, actor = _clinic_and_actor(request)
    attachment = download_attachment(
        clinic_id=clinic_id,
        actor=actor,
        attachment_id=attachment_id,
        request_id=_request_uuid(),
    )
    response = FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=attachment.original_name,
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def attachment_delete(request: HttpRequest, attachment_id: UUID) -> HttpResponse:
    """Delete one authorized attachment and audit the action (8.8.5.4)."""
    clinic_id, actor = _clinic_and_actor(request)
    delete_attachment(
        clinic_id=clinic_id,
        actor=actor,
        attachment_id=attachment_id,
        request_id=_request_uuid(),
    )
    next_url = request.POST.get("next") or reverse("conversation_list")
    return HttpResponseRedirect(next_url)
