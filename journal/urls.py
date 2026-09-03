"""URL routes for the patient journal domain."""

from django.urls import path

from .views import (
    checkin_list,
    checkin_today,
    journal_create,
    journal_detail,
    journal_edit,
    journal_list,
    journal_request_access_view,
    journal_respond_access_request_view,
    journal_revoke_sharing_view,
    journal_set_visibility,
)

urlpatterns = [
    path("", journal_list, name="journal_list"),
    path("novo/", journal_create, name="journal_create"),
    path("<uuid:entry_id>/", journal_detail, name="journal_detail"),
    path("<uuid:entry_id>/editar/", journal_edit, name="journal_edit"),
    path(
        "<uuid:entry_id>/visibilidade/",
        journal_set_visibility,
        name="journal_set_visibility",
    ),
    path(
        "<uuid:entry_id>/revogar/",
        journal_revoke_sharing_view,
        name="journal_revoke_sharing",
    ),
    path(
        "<uuid:entry_id>/solicitar-acesso/",
        journal_request_access_view,
        name="journal_request_access",
    ),
    path(
        "solicitacoes/<uuid:access_request_id>/responder/",
        journal_respond_access_request_view,
        name="journal_respond_access_request",
    ),
    path("checkin/", checkin_today, name="checkin_today"),
    path("checkin/historico/", checkin_list, name="checkin_list"),
]
