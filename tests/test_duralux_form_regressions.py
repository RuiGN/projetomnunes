"""Duralux controls must retain form semantics and usable group geometry."""

from html.parser import HTMLParser

from django import forms

from core.templatetags.accessible_forms import accessible_widget


class Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))


def test_choice_group_wrapper_is_not_styled_as_a_single_checkbox() -> None:
    class ChoicesForm(forms.Form):
        channels = forms.MultipleChoiceField(
            choices=[("email", "E-mail"), ("phone", "Telefone")],
            widget=forms.CheckboxSelectMultiple,
        )

    parser = Elements()
    parser.feed(accessible_widget(ChoicesForm()["channels"]))
    wrapper = next(attrs for tag, attrs in parser.elements if tag == "div")
    assert "form-check-input" not in (wrapper.get("class") or "").split()
    inputs = [attrs for tag, attrs in parser.elements if tag == "input"]
    assert len(inputs) == 2
    assert all(
        "form-check-input" in (attrs.get("class") or "").split() for attrs in inputs
    )


def test_onboarding_uses_duralux_field_rendering() -> None:
    from django.template.loader import render_to_string

    from onboarding.forms import PatientGoalsForm

    html = render_to_string(
        "onboarding/patient_onboarding.html",
        {
            "form": PatientGoalsForm(),
            "step": "goals",
            "layout_template": "layouts/vertical.html",
            "user": {"email": "synthetic@example.test"},
        },
    )
    parser = Elements()
    parser.feed(html)
    field = next(
        attrs
        for tag, attrs in parser.elements
        if tag == "textarea" and attrs.get("name") == "goals"
    )
    assert "form-control" in (field.get("class") or "").split()


def test_patient_form_renders_duralux_controls_and_existing_error_targets() -> None:
    from django.template.loader import render_to_string

    from people.forms import PatientProfileForm

    form = PatientProfileForm(data={})
    html = render_to_string(
        "people/patient_form.html",
        {
            "form": form,
            "layout_template": "layouts/vertical.html",
            "user": {"email": "synthetic@example.test"},
        },
    )
    parser = Elements()
    parser.feed(html)
    elements = parser.elements
    ids = {attrs.get("id") for _, attrs in elements}
    name = next(
        attrs
        for tag, attrs in elements
        if tag == "input" and attrs.get("name") == "full_name"
    )
    assert "form-control" in (name.get("class") or "").split()
    assert name.get("aria-invalid") == "true"
    assert name.get("aria-describedby")
    assert all(target in ids for target in str(name["aria-describedby"]).split())


def test_sprint6_visibility_help_targets_exist_and_enums_are_not_visible() -> None:
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags

    from goals.forms import GoalForm
    from journal.forms import JournalEntryForm

    cases = (
        ("journal/form.html", JournalEntryForm(), "Novo registro"),
        ("goals/form.html", GoalForm(data={}), "Nova meta"),
    )
    for template_name, form, page_title in cases:
        html = render_to_string(
            template_name,
            {
                "form": form,
                "form_id": "review-form",
                "layout_template": "layouts/vertical.html",
                "page_title": page_title,
                "submit_label": "Salvar",
                "user": {"email": "synthetic@example.test"},
            },
        )
        parser = Elements()
        parser.feed(html)
        ids = {attrs.get("id") for _, attrs in parser.elements}
        described_elements = [
            attrs
            for _, attrs in parser.elements
            if attrs.get("aria-describedby")
        ]
        assert described_elements, template_name
        for field in described_elements:
            described_by = str(field["aria-describedby"]).split()
            assert all(target in ids for target in described_by), template_name

        visibility_inputs = [
            attrs
            for tag, attrs in parser.elements
            if tag == "input" and attrs.get("name") == "visibility"
        ]
        assert visibility_inputs, template_name
        for field in visibility_inputs:
            described_by = str(field.get("aria-describedby") or "").split()
            assert described_by, template_name
            assert all(target in ids for target in described_by), template_name

        if template_name == "journal/form.html":
            for field_name in ("mood", "emotions"):
                inputs = [
                    attrs
                    for tag, attrs in parser.elements
                    if tag == "input" and attrs.get("name") == field_name
                ]
                assert inputs, field_name
                assert all(
                    attrs.get("aria-describedby") for attrs in inputs
                ), field_name

        visible_text = strip_tags(html)
        for enum_value in ("shareable", "confirmation_required", "private"):
            assert enum_value not in visible_text, (template_name, enum_value)
