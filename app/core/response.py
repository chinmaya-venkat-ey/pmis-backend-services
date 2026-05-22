"""HAL+JSON envelope formatters — canonical wire shape for all responses.

Duplicated from project-management. Keep in sync across all PMIS services.
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
    items = list(elements)
    links: dict[str, dict] = {}
    if base_path:
        links["self"] = {"href": f"{base_path}?offset={offset}&pageSize={page_size}"}
        last_page = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
        if offset < last_page:
            links["next"] = {"href": f"{base_path}?offset={offset + 1}&pageSize={page_size}"}
        if last_page > 1:
            links["last"] = {"href": f"{base_path}?offset={last_page}&pageSize={page_size}"}
    elif self_link:
        links["self"] = {"href": self_link}
    if extra_links:
        links.update(extra_links)
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
    body = {"_type": "Error", "errorIdentifier": code, "message": message}
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
    body = {"data": data, "message": message, "error": error, "status": status}
    return JSONResponse(
        status_code=status,
        content=jsonable_encoder(body),
        headers=headers,
    )
