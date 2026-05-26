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
    """Wrap a flat resource dict in the HAL ``_type`` + ``_links`` envelope.

    Monolith parity: when no self_link and no extra_links are provided
    (e.g. the comment ``Success`` envelope returned from DELETE) we
    OMIT the ``_links`` key entirely — emitting ``"_links": {}`` is a
    visible divergence on the wire.
    """
    links: dict[str, dict] = {}
    if self_link:
        links["self"] = {"href": self_link}
    if extra_links:
        links.update(extra_links)
    out: dict[str, Any] = {"_type": _type}
    if links:
        out["_links"] = links
    out.update(attributes)
    return out


def hal_collection(
    elements: Iterable[dict],
    total: int,
    *,
    offset: int = 1,
    page_size: int = 20,
    self_link: Optional[str] = None,
    base_path: Optional[str] = None,
    extra_links: Optional[dict[str, dict]] = None,
) -> dict:
    """Wrap an iterable of elements in the HAL Collection envelope.

    When ``base_path`` is provided (path without query string), the
    function auto-generates ``self`` / ``next`` / ``last`` links with
    ``?offset=X&pageSize=Y`` query strings — matches the monolith's
    ``format_*_collection`` HAL pagination shape.
    """
    items = list(elements)
    links: dict[str, dict] = {}
    if base_path:
        links["self"] = {
            "href": f"{base_path}?offset={offset}&pageSize={page_size}",
        }
        last_page = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
        if offset < last_page:
            links["next"] = {
                "href": f"{base_path}?offset={offset + 1}&pageSize={page_size}",
            }
        if last_page > 1:
            links["last"] = {
                "href": f"{base_path}?offset={last_page}&pageSize={page_size}",
            }
    elif self_link:
        links["self"] = {"href": self_link}
    if extra_links:
        links.update(extra_links)
    # Monolith parity: when a caller suppresses ``base_path`` (e.g. the
    # COMMENT list path) the collection emits NO top-level ``_links`` key
    # at all — not ``"_links": {}``. Only include ``_links`` when at
    # least one link was synthesised.
    out: dict[str, Any] = {"_type": "Collection"}
    if links:
        out["_links"] = links
    out.update({
        "total": total,
        "count": len(items),
        "pageSize": page_size,
        "offset": offset,
        "_embedded": {"elements": items},
    })
    return out


def format_error(
    code: str,
    message: str,
    details: Optional[Any] = None,
) -> dict:
    """Inner error body — matches the monolith's HAL Error shape.

    Default envelope is ``{_type, errorIdentifier, message}``.
    Monolith emits ``_embedded.details`` only when an endpoint
    explicitly populates it with a sub-code or structured context
    (e.g. publish: ``{errorIdentifier: "no_milestones"}``). When
    ``details`` is falsy we omit the block entirely so simple
    validation/not-found errors carry the bare 3-key envelope the
    monolith returns.
    """
    body = {
        "_type": "Error",
        "errorIdentifier": code,
        "message": message,
    }
    if details:
        body["_embedded"] = {"details": details}
    return body


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
