"""HAL+JSON envelope formatters — canonical wire shape for all responses.

Outer envelope (always)::

    {
      "data":    <object | array | null>,
      "message": <string | null>,
      "error":   <error object | null>,
      "status":  <int>
    }

Inner shapes (HAL+JSON, OpenProject v3 contract)::

    Resource::    {"_type": "<Kind>", "_links": {...}, **attrs}
    Collection::  {"_type": "Collection", "_links": {...},
                   "total", "count", "offset", "pageSize",
                   "_embedded": {"elements": [...]}}
    Error::       {"_type": "Error", "errorIdentifier": "<code>",
                   "message": "...", "_embedded": {"details": {...}}}

Wiring:
  - ``app.core.api_route.HalApiRoute`` wraps every successful response
    automatically — handlers / controllers don't call these helpers.
  - ``app.middleware.error_handler`` uses ``format_error`` + ``api_response``
    on the failure path.

Duplicated across all 4 services (microservice isolation) — keep in sync.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def hal_resource(
    _type: str,
    attributes: dict[str, Any],
    *,
    self_link: Optional[str] = None,
    extra_links: Optional[dict[str, dict]] = None,
) -> dict:
    """Wrap a flat resource dict in the HAL ``_type`` + ``_links`` envelope."""
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
    page_size: Optional[int] = 20,
    self_link: Optional[str] = None,
    extra_links: Optional[dict[str, dict]] = None,
) -> dict:
    """Wrap an iterable of elements in the HAL Collection envelope."""
    items = list(elements)
    if page_size is None:
        # No pagination cap requested (pageSize omitted) -> present the
        # whole result set as a single page.
        page_size = total if total and total > 0 else len(items)
    links: dict[str, dict] = {}
    if self_link:
        links["self"] = {"href": self_link}
    if extra_links:
        links.update(extra_links)
    return {
        "_type": "Collection",
        "_links": links,
        "total": total,
        "count": len(items),
        "pageSize": page_size,
        "offset": offset,
        "_embedded": {"elements": items},
    }


def format_error(
    code: str,
    message: str,
    details: Optional[Any] = None,
) -> dict:
    """Inner error body — matches the monolith's HAL Error shape."""
    return {
        "_type": "Error",
        "errorIdentifier": code,
        "message": message,
        "_embedded": {"details": details if details is not None else {}},
    }


def api_response(
    *,
    data: Any = None,
    message: Optional[str] = None,
    error: Optional[dict] = None,
    status: int = 200,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    """Build the canonical outer envelope and return a FastAPI JSONResponse.

    On success, set ``data`` (and optional ``message``). On failure, set
    ``error`` (built by ``format_error``). Never both.
    """
    body = {
        "data": data,
        "message": message,
        "error": error,
        "status": status,
    }
    return JSONResponse(
        status_code=status,
        content=jsonable_encoder(body),
        headers=headers,
    )
