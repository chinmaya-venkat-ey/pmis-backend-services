"""HAL envelope formatters for pmis-masters-management.

WARNING: Duplicated across services per PLAN.md §6.1. Canonical location
will be services/pmis-user-management/app/core/response.py once user-svc
is ported. Keep in sync by hand until tools/check_canonical_drift.py is
wired.

Conventions:
  - Single resource: bare dict OR HAL `{"_type": "<Name>", "_links": {...}, ...attrs}`
  - Collection:      `{"_type": "Collection", "_embedded": {"elements": [...]}, "total": N, "count": M, "pageSize": P, "offset": O, "_links": {...}}`
  - Error:           `{"code": "...", "message": "...", "details": {...}, "request_id": "..."}`
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


def hal_resource(
    _type: str,
    attributes: dict[str, Any],
    *,
    self_link: Optional[str] = None,
    extra_links: Optional[dict[str, dict]] = None,
) -> dict:
    """Build a single-resource HAL envelope."""
    links: dict[str, dict] = {}
    if self_link:
        links["self"] = {"href": self_link}
    if extra_links:
        links.update(extra_links)
    return {
        "_type": _type,
        "_links": links,
        **attributes,
    }


def hal_collection(
    elements: Iterable[dict],
    total: int,
    *,
    offset: int = 1,
    page_size: int = 20,
    self_link: Optional[str] = None,
) -> dict:
    """Build a Collection HAL envelope. `offset` is 1-based."""
    items = list(elements)
    return {
        "_type": "Collection",
        "_embedded": {"elements": items},
        "total": total,
        "count": len(items),
        "pageSize": page_size,
        "offset": offset,
        "_links": ({"self": {"href": self_link}} if self_link else {}),
    }


def error_envelope(
    code: str,
    message: str,
    details: Optional[dict] = None,
) -> dict:
    """Build an error envelope. The exception handler injects `request_id`."""
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def ok_envelope(data: Any = None, *, message: str = "OK") -> dict:
    payload: dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return payload
