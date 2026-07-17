"""Shared helpers for XCP-ng AIops ops modules.

Xen Orchestra REST ``/rest/v0`` collection endpoints return a bare JSON array
(of objects when ``fields=`` is passed, of href strings otherwise); a few wrap
results in ``{"data": [...]}``. ``as_list`` normalises all of these to a list
of dicts. All API-returned text reaches the caller only after ``sanitize()``
(output hygiene).
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.governance import sanitize

# The field sets ops modules request from XO — asking for fields makes the
# collection endpoints return objects instead of href strings.


def as_list(data: Any) -> list[dict]:
    """Normalise a collection endpoint's payload to a list of dicts."""
    if isinstance(data, dict):
        items = data.get("data", [])
    else:
        items = data
    return [i for i in (items or []) if isinstance(i, dict)]


def s(value: Any, limit: int = 128) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)


def pct(used: Any, total: Any) -> float | None:
    """Percentage used/total rounded to 1 decimal, or None when not computable."""
    if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total:
        return round(used / total * 100, 1)
    return None
