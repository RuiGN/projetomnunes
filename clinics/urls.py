"""Tenant-scoped clinic setup routes."""

from django.urls import path

from .views import clinic_setup, whitelabel_domains

urlpatterns = [
    path("setup/", clinic_setup, name="clinic_setup"),
    path("white-label/dominios/", whitelabel_domains, name="whitelabel_domains"),
]
