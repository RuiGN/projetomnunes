"""Small, defensive filters for presentation-only template structures."""

from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.filter
def at_index(sequence: object, index: object) -> Any:
    """Return one sequence item or an empty string for malformed input."""
    try:
        if not isinstance(index, int):
            index = int(str(index))
        return sequence[index]  # type: ignore[index]
    except IndexError, KeyError, TypeError, ValueError:
        return ""
