"""URL routes for the scheduling domain."""

from django.urls import path

from .unit_views import (
    room_create,
    room_deactivate,
    unit_create,
    unit_deactivate,
    unit_list,
    unit_update,
)
from .views import (
    appointment_calendar,
    appointment_cancel,
    appointment_complete,
    appointment_confirm,
    appointment_list,
    appointment_no_show,
    appointment_request,
    appointment_reschedule,
    attachment_delete,
    attachment_download,
    conversation_create,
    conversation_detail,
    conversation_list,
    reminder_preferences,
)
from .waitlist_views import (
    waitlist_add,
    waitlist_cancel,
    waitlist_fill,
    waitlist_list,
)

urlpatterns = [
    # Agenda / appointments (8.8.1 & 8.8.2)
    path("", appointment_list, name="appointment_list"),
    path("semana/", appointment_calendar, name="appointment_calendar"),
    path("consultas/nova/", appointment_request, name="appointment_request"),
    path(
        "consultas/<uuid:appointment_id>/confirmar/",
        appointment_confirm,
        name="appointment_confirm",
    ),
    path(
        "consultas/<uuid:appointment_id>/remarcar/",
        appointment_reschedule,
        name="appointment_reschedule",
    ),
    path(
        "consultas/<uuid:appointment_id>/cancelar/",
        appointment_cancel,
        name="appointment_cancel",
    ),
    path(
        "consultas/<uuid:appointment_id>/concluir/",
        appointment_complete,
        name="appointment_complete",
    ),
    path(
        "consultas/<uuid:appointment_id>/falta/",
        appointment_no_show,
        name="appointment_no_show",
    ),
    # Reminders (8.8.3)
    path("lembretes/", reminder_preferences, name="reminder_preferences"),
    # Messaging (8.8.4 & 8.8.5)
    path("mensagens/", conversation_list, name="conversation_list"),
    path("mensagens/nova/", conversation_create, name="conversation_create"),
    path(
        "mensagens/<uuid:conversation_id>/",
        conversation_detail,
        name="conversation_detail",
    ),
    path(
        "anexos/<uuid:attachment_id>/baixar/",
        attachment_download,
        name="attachment_download",
    ),
    path(
        "anexos/<uuid:attachment_id>/excluir/",
        attachment_delete,
        name="attachment_delete",
    ),
    # Waitlist (8.10.4.2)
    path("espera/", waitlist_list, name="waitlist_list"),
    path("espera/nova/", waitlist_add, name="waitlist_add"),
    path(
        "espera/<uuid:entry_id>/cancelar/",
        waitlist_cancel,
        name="waitlist_cancel",
    ),
    path(
        "espera/<uuid:entry_id>/encaixar/",
        waitlist_fill,
        name="waitlist_fill",
    ),
    # Units and rooms (8.10.1)
    path("unidades/", unit_list, name="unit_list"),
    path("unidades/nova/", unit_create, name="unit_create"),
    path("unidades/<uuid:unit_id>/editar/", unit_update, name="unit_update"),
    path(
        "unidades/<uuid:unit_id>/inativar/",
        unit_deactivate,
        name="unit_deactivate",
    ),
    path("salas/nova/", room_create, name="room_create"),
    path("salas/<uuid:room_id>/inativar/", room_deactivate, name="room_deactivate"),
]
