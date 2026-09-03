"""Safe presentation helpers shared by server-rendered components."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from urllib.parse import urlencode


def build_query_url(
    query: Mapping[str, str],
    *,
    overrides: Mapping[str, str],
    allowed_keys: Collection[str],
) -> str:
    """Return a deterministic query string containing only allowed scalar values."""
    allowed = set(allowed_keys)
    values = {
        key: value
        for key, value in query.items()
        if key in allowed and isinstance(value, str) and value
    }
    for key, value in overrides.items():
        if key not in allowed:
            continue
        if isinstance(value, str) and value:
            values[key] = value
        else:
            values.pop(key, None)
    if not values:
        return ""
    return f"?{urlencode(sorted(values.items()))}"
