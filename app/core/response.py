"""HAL envelope formatters for consistent response shapes.

Conventions (PLAN.md §2.6):
  - Single resource: bare dict OR HAL `{"_type": "<Name>", "_links": {...}, ...attrs}`
  - Collection:      `{"_type": "Collection", "_embedded": {"elements": [...]}, "total": N, "count": M, "pageSize": P, "offset": O, "_links": {...}}`
  - Error:           `{"code": "...", "message": "...", "details": {...}, "request_id": "..."}`

NOTE: notification-svc is the internal/trust-boundary service. It keeps
the terse flat shape rather than the canonical PMIS envelope used by the
FE-facing services (user/project/masters) — its only callers are other
services that check ``resp.status_code`` and don't read the body.
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
    """Build a Collection HAL envelope.

    `offset` is 1-based (matches monolith convention).
    """
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
    """Build an error envelope (request_id is added by the exception handler)."""
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def ok_envelope(data: Any = None, *, message: str = "OK") -> dict:
    """Optional success-wrapping envelope. Most endpoints return data directly;
    use this only when the caller benefits from a normalized success shape
    (e.g. action endpoints where the response is "did it work?")."""
    payload: dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return payload
