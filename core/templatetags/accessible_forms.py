"""Template helpers for accessible Django form rendering."""

from __future__ import annotations

from django import forms, template
from django.forms.boundfield import BoundField
from django.utils.safestring import SafeString, mark_safe

register = template.Library()


@register.filter
def accessible_widget(field: BoundField) -> SafeString:
    """Render a bound field with deterministic accessibility attributes."""
    widget = field.field.widget
    input_type = getattr(widget, "input_type", "")
    described_by: list[str] = []
    if field.errors:
        described_by.extend(
            f"{field.auto_id}_error_{index}"
            for index, _error in enumerate(field.errors)
        )
    if field.help_text:
        described_by.append(f"{field.auto_id}_helptext")

    attrs: dict[str, str | bool] = {}
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)
    if field.errors:
        attrs["aria-invalid"] = "true"

    if input_type not in {"checkbox", "radio"}:
        attrs["class"] = "form-control"
    render_widget = widget
    if isinstance(field.field, forms.DateField):
        render_widget = forms.DateInput(
            attrs=widget.attrs,
            format="%Y-%m-%d",
        )
        render_widget.input_type = "date"
    if field.name == "phone":
        attrs.update(
            {
                "data-mask": "phone",
                "data-canonical-value": "",
                "inputmode": "tel",
                "autocomplete": "tel",
            }
        )
    elif field.name == "document":
        attrs.update(
            {
                "data-mask": "document",
                "data-canonical-value": "",
                "inputmode": "numeric",
                "autocomplete": "off",
            }
        )
    if field.name == "enabled":
        attrs["class"] = "switch-input"
        attrs["role"] = "switch"

    return mark_safe(field.as_widget(widget=render_widget, attrs=attrs))


@register.filter
def error_target_id(field: BoundField) -> str:
    """Return the focusable error-summary destination for a bound field."""
    if isinstance(field.field.widget, forms.RadioSelect):
        return f"{field.auto_id}_0"
    return field.auto_id
