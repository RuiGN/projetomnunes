"""English-language routes for people management."""

from django.urls import path

from .views import (
    patient_create,
    patient_detail,
    patient_invite,
    patient_list,
    professional_list,
    professional_reactivate,
    professional_suspend,
)

urlpatterns = [
    path("patients/", patient_list, name="patient_list"),
    path("patients/new/", patient_create, name="patient_create"),
    path(
        "patients/<uuid:patient_profile_id>/invite/",
        patient_invite,
        name="patient_invite",
    ),
    path(
        "patients/<uuid:patient_profile_id>/",
        patient_detail,
        name="patient_detail",
    ),
    path("professionals/", professional_list, name="professional_list"),
    path(
        "professionals/<uuid:membership_id>/suspend/",
        professional_suspend,
        name="professional_suspend",
    ),
    path(
        "professionals/<uuid:membership_id>/reactivate/",
        professional_reactivate,
        name="professional_reactivate",
    ),
]
