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
