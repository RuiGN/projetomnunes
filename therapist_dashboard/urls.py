"""Routes for the therapist dashboard domain."""

from django.urls import path

from .views import therapist_dashboard

urlpatterns = [
    path("", therapist_dashboard, name="therapist_dashboard"),
]
