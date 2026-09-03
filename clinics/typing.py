"""Typed request surface for clinic-aware handlers."""

from django.http import HttpRequest

from clinics.models import Clinic


class ClinicRequest(HttpRequest):
    """An HTTP request after clinic tenant middleware has run."""

    clinic: Clinic | None
