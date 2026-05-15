"""HAL envelope formatters for pmis-project-management.

Duplicates services/pmis-user-management/app/core/response.py — keep in sync.
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
