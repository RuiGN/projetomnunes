"""Accessible contracts for reusable Django form components."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from django import forms
from django.conf import settings
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from clinics.models import ClinicMembership
from core.forms import DesignSystemExampleForm
from tests.factories import ClinicFactory, ClinicMembershipFactory, UserFactory


class ComponentExampleForm(forms.Form):
    full_name = forms.CharField(
        label="Nome completo", help_text="Como consta no cadastro."
    )
    category = forms.ChoiceField(
        label="Categoria", choices=(("individual", "Individual"), ("group", "Grupo"))
    )
    start_date = forms.DateField(label="Data de início", widget=forms.DateInput())
    phone = forms.CharField(label="Telefone", required=False)
    document = forms.CharField(label="Documento", required=False)
    notes = forms.CharField(label="Observações", widget=forms.Textarea, required=False)
    confirmed = forms.BooleanField(label="Confirmo os dados", required=False)
    contact_method = forms.ChoiceField(
        label="Contato preferencial",
        choices=(("email", "E-mail"), ("phone", "Telefone")),
        widget=forms.RadioSelect,
    )
    enabled = forms.BooleanField(label="Recurso ativo", required=False)
    attachment = forms.FileField(label="Anexo", required=False)


def _render_form(form: forms.Form, **extra: object) -> str:
    return render_to_string(
        "components/form.html",
        {
            "form": form,
            "form_id": "component-form",
            "submit_label": "Salvar alterações",
            **extra,
        },
    )


def test_form_component_renders_labels_help_and_supported_widgets() -> None:
    content = _render_form(ComponentExampleForm())

    assert '<form id="component-form"' in content
    assert "novalidate" in content
    assert 'enctype="multipart/form-data"' in content
    for field_name in (
        "full_name",
        "category",
        "start_date",
        "phone",
        "document",
        "notes",
        "confirmed",
        "contact_method",
        "enabled",
        "attachment",
    ):
        assert f'id="id_{field_name}"' in content
    assert 'for="id_full_name"' in content
    assert 'id="id_full_name_helptext"' in content
    assert 'aria-describedby="id_full_name_helptext"' in content
    assert 'type="radio"' in content
    date_input = re.search(r'<input[^>]+id="id_start_date"[^>]*>', content)
    assert date_input is not None
    assert date_input.group(0).count('type="date"') == 1
    assert 'type="text"' not in date_input.group(0)
    assert 'type="file"' in content
    assert ">Salvar alterações<" in content


def test_form_component_uses_duralux_bootstrap_classes() -> None:
    content = _render_form(ComponentExampleForm())

    assert 'class="d-grid gap-3"' in content
    assert 'class="mb-3"' in content
    assert 'class="form-label"' in content
    assert 'class="form-check-input"' in content
    assert 'class="form-check form-switch"' in content
    assert 'class="btn btn-primary"' in content
    for legacy_class in (
        "form-stack",
        "form-field",
        "choice-group",
        "switch-control",
        "choice-control",
        "primary-action",
    ):
        assert legacy_class not in content


def test_unbound_date_initial_uses_html_date_canonical_value() -> None:
    content = _render_form(
        ComponentExampleForm(initial={"start_date": date(2026, 8, 31)})
    )

    date_input = re.search(r'<input[^>]+id="id_start_date"[^>]*>', content)
    assert date_input is not None
    assert 'value="2026-08-31"' in date_input.group(0)
    assert 'value="31/08/2026"' not in date_input.group(0)


def test_invalid_form_has_error_summary_focus_target_and_field_connections() -> None:
    form = ComponentExampleForm(data={"full_name": "", "category": "invalid"})
    assert not form.is_valid()

    content = _render_form(form)

    assert 'class="alert alert-danger"' in content
    assert 'role="alert"' in content
    assert 'tabindex="-1"' in content
    assert "data-focus-error-summary" in content
    assert 'href="#id_full_name"' in content
    assert 'aria-invalid="true"' in content
    assert 'aria-describedby="id_full_name_error' in content
    assert "Este campo é obrigatório." in content
    assert 'href="#id_contact_method_0"' in content


def test_masked_fields_keep_canonical_submission_and_accessible_input_modes() -> None:
    content = _render_form(ComponentExampleForm())

    assert 'data-mask="phone"' in content
    assert 'data-mask="document"' in content
    assert 'inputmode="tel"' in content
    assert 'inputmode="numeric"' in content
    assert "data-canonical-value" in content


def test_server_normalizes_masked_values_to_canonical_digits() -> None:
    form = DesignSystemExampleForm(
        data={
            "display_name": "Unidade Centro",
            "category": "individual",
            "start_date": "2026-08-31",
            "phone": "(11) 98765-4321",
            "document": "123.456.789-00",
            "contact_method": "email",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone"] == "11987654321"
    assert form.cleaned_data["document"] == "12345678900"


def test_server_rejects_digits_hidden_by_visual_mask_limits() -> None:
    form = DesignSystemExampleForm(
        data={
            "display_name": "Unidade Centro",
            "category": "individual",
            "start_date": "2026-08-31",
            "phone": "119876543210",
            "document": "123456789012345",
            "contact_method": "email",
        }
    )

    assert not form.is_valid()
    assert "phone" in form.errors
    assert "document" in form.errors


def test_form_guards_duplicate_unsaved_and_destructive_actions() -> None:
    content = _render_form(
        ComponentExampleForm(),
        destructive_action={
            "label": "Excluir configuração",
            "confirmation": "Excluir esta configuração?",
        },
    )
    script = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "js"
        / "form-behaviors.js"
    ).read_text(encoding="utf-8")

    assert "data-form-guard" in content
    assert 'data-dirty-message="Há alterações não salvas."' in content
    assert "data-destructive-action" in content
    assert 'data-confirmation="Excluir esta configuração?"' in content
    assert 'name="action"' in content
    assert 'value="delete"' in content
    assert "requestSubmit(button)" in script
    assert "beforeunload" in script
    assert "data-submitting" in script
    assert "canonicalValue" in script
    assert "canonicalize(input).slice(0, maxDigits)" in script
    assert "window.confirm" in script
    assert ".value = canonicalValue" in script


def test_form_css_supports_focus_errors_switches_and_mobile_layout() -> None:
    css = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "css"
        / "product-integration.css"
    ).read_text(encoding="utf-8")

    for selector in (
        ".product-form-card",
        ".product-workspace-body",
        ".form-control",
        ".alert-danger",
        ".invalid-feedback",
        ".form-check-input",
        ".form-switch",
        ".form-actions",
        ".btn-primary",
        ".btn-outline-primary",
    ):
        assert selector in css
    assert ":focus-visible" in css
    assert "var(--bs-danger)" in css
    assert "min-height: 44px" in css
    assert "@media (max-width: 767.98px)" in css


@pytest.mark.parametrize("unsafe", ("<script>alert(1)</script>", '" onfocus="alert(1)'))
def test_form_component_escapes_user_controlled_values(unsafe: str) -> None:
    form = ComponentExampleForm(data={"full_name": unsafe, "category": "individual"})
    form.is_valid()

    content = _render_form(form)

    assert "<script>alert(1)</script>" not in content
    assert 'onfocus="alert(1)' not in content


@pytest.mark.django_db
def test_visual_reference_catalogs_the_accessible_form(client: Client) -> None:
    user = UserFactory.create(is_staff=True)
    clinic = ClinicFactory.create(name="Clínica Formulários")
    ClinicMembershipFactory.create(
        user=user,
        clinic=clinic,
        role=ClinicMembership.Role.CLINIC_ADMIN,
    )
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.get(reverse("design_system_reference"))
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Formulário acessível" in content
    assert 'id="reference-form"' in content
    assert "Nome de exibição" in content
    assert "Telefone" in content
    assert "Documento" in content
    assert "Contato preferencial" in content
    assert "Anexo" in content


@pytest.mark.django_db
def test_visual_reference_validates_posted_form_on_the_server(client: Client) -> None:
    user = UserFactory.create(is_staff=True)
    clinic = ClinicFactory.create(name="Clínica Validação")
    ClinicMembershipFactory.create(user=user, clinic=clinic)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("design_system_reference"),
        {"display_name": "", "category": "invalid", "contact_method": ""},
    )
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Revise os campos indicados" in content
    assert 'aria-invalid="true"' in content
    assert "Exemplo validado pelo servidor" not in content


@pytest.mark.django_db
def test_visual_reference_reports_a_valid_server_submission(client: Client) -> None:
    user = UserFactory.create(is_staff=True)
    clinic = ClinicFactory.create(name="Clínica Exemplo Válido")
    ClinicMembershipFactory.create(user=user, clinic=clinic)
    client.force_login(user)
    session = client.session
    session["active_clinic_id"] = str(clinic.pk)
    session.save()

    response = client.post(
        reverse("design_system_reference"),
        {
            "display_name": "Unidade Centro",
            "category": "individual",
            "start_date": "2026-08-31",
            "phone": "(11) 98765-4321",
            "document": "123.456.789-00",
            "contact_method": "email",
        },
    )

    assert response.status_code == 200
    assert "Exemplo validado pelo servidor" in response.content.decode("utf-8")


def test_form_script_focuses_first_invalid_field_and_recovers_from_bfcache() -> None:
    script = (
        Path(settings.BASE_DIR)
        / "static"
        / "duralux"
        / "js"
        / "form-behaviors.js"
    ).read_text(encoding="utf-8")

    assert 'document.querySelector("[aria-invalid=\\"true\\"]")?.focus()' in script
    assert 'addEventListener("pageshow"' in script
