"""URL routes for the analytics domain."""

from django.urls import path

from .views import (
    clinic_panel,
    patient_dashboard,
    report_download,
    report_generate,
    report_list,
    therapist_dashboard,
)

urlpatterns = [
    path("", patient_dashboard, name="patient_dashboard"),
    path("profissional/", therapist_dashboard, name="therapist_dashboard"),
    path("clinica/", clinic_panel, name="clinic_panel"),
    path("relatorios/", report_list, name="report_list"),
    path("relatorios/gerar/", report_generate, name="report_generate"),
    path(
        "relatorios/<uuid:report_id>/baixar/",
        report_download,
        name="report_download",
    ),
]
