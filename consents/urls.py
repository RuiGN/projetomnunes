"""URL routes for reviewing and recording versioned consent decisions."""

from django.urls import path

from .views import (
    acknowledge_revocation_work,
    consent_center,
    consent_decide,
    consent_revoke,
    revocation_work_queue,
)

urlpatterns = [
    path("", consent_center, name="consent_center"),
    path(
        "operations/revocations/",
        revocation_work_queue,
        name="consent_revocation_work_queue",
    ),
    path(
        "operations/revocations/<uuid:work_item_id>/acknowledge/",
        acknowledge_revocation_work,
        name="consent_revocation_work_acknowledge",
    ),
    path("<uuid:document_id>/decision/", consent_decide, name="consent_decide"),
    path("<uuid:document_id>/revoke/", consent_revoke, name="consent_revoke"),
]
