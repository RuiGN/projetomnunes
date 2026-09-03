"""Admin infrastructure regressions for clinic tenant models."""

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from clinics.admin import ClinicMembershipAdmin
from clinics.models import Clinic, ClinicMembership

pytestmark = pytest.mark.django_db


def test_membership_admin_form_uses_infrastructure_clinic_queryset() -> None:
    """Building the membership form can enumerate clinics only inside admin."""
    clinic = Clinic.infrastructure_objects.create(name="Clínica Admin", slug="admin")
    request = RequestFactory().get("/admin/clinics/clinicmembership/add/")
    model_admin = ClinicMembershipAdmin(ClinicMembership, AdminSite())

    form_class = model_admin.get_form(request)
    clinic_field = form_class.base_fields["clinic"]

    assert isinstance(clinic_field, forms.ModelChoiceField)
    assert clinic_field.queryset is not None
    assert list(clinic_field.queryset) == [clinic]
