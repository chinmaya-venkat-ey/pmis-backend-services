"""HalApiRoute — custom APIRoute that auto-wraps successful responses in
the canonical PMIS envelope with HAL+JSON inner shapes.

How it works:
  - Handlers / controllers stay unchanged. Pydantic ``response_model``
    still validates + serializes on the way out (including the IST
    coercion on ``app.schemas._base.ResponseModel``).
  - This route class intercepts the resulting ``JSONResponse``, decodes
    the body, wraps it via ``hal_resource`` / ``hal_collection``, and
    re-emits via ``api_response``.
  - ``StreamingResponse`` (file downloads) and non-JSON ``Response``
    returns pass through untouched.
  - Health / readiness routes are excluded at registration time (see
    ``install_hal_route_class`` below), so orchestrators see the raw
    ``{"status": "ok"}`` shape they expect.

``_type`` resolution: derived from the route's ``response_model`` class
name (``ProjectResponse`` → ``"Project"``). A schema can override with
``_hal_type: ClassVar[str] = "X"``.

Duplicated across all 4 services — keep in sync.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.routing import request_response

from app.core.response import api_response, hal_collection, hal_resource


_ENVELOPE_KEYS = frozenset({"data", "message", "error", "status"})

# Header names that JSONResponse will recompute from the new body — must
# not be carried over when we re-emit, or we'll send a wrong Content-Length.
_STALE_HEADERS = frozenset({"content-length", "content-type"})


def _hal_type_for(response_model: Optional[type]) -> str:
    """Derive the HAL ``_type`` from a Pydantic response model class.

    ``ProjectResponse`` → ``"Project"``. Override on the schema with
    ``_hal_type: ClassVar[str] = "X"`` if a custom name is needed.
    """
    if response_model is None:
        return "Resource"
    explicit = getattr(response_model, "_hal_type", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    name = getattr(response_model, "__name__", "")
    if name.endswith("Response"):
        return name[: -len("Response")] or "Resource"
    return name or "Resource"


def _looks_like_paged_dict(value: Any) -> bool:
    """The ``{items, total, offset, page_size}`` shape returned by a few
    list endpoints (project list, milestone list, etc.)."""
    return (
        isinstance(value, dict)
        and "items" in value
        and "total" in value
    )


def _wrap(value: Any, hal_type: str) -> Optional[dict]:
    """Convert a Pydantic-serialized body into the appropriate HAL inner
    shape. Returns the value to put under ``data``."""
    if value is None:
        return None

    if _looks_like_paged_dict(value):
        items = value["items"] or []
        return hal_collection(
            items,
            total=int(value["total"]),
            offset=int(value.get("offset", 1)),
            page_size=int(value.get("page_size", len(items))),
        )

    if isinstance(value, list):
        return hal_collection(
            value,
            total=len(value),
            offset=1,
            page_size=len(value),
        )

    if isinstance(value, dict):
        # If the handler already produced an envelope, surface as-is.
        if _ENVELOPE_KEYS <= set(value.keys()):
            return value
        return hal_resource(hal_type, value)

    # Scalar / unexpected — wrap minimally so the envelope stays valid.
    return {"_type": hal_type, "value": value}


class HalApiRoute(APIRoute):
    """APIRoute that wraps successful responses in the PMIS envelope."""

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()
        hal_type = _hal_type_for(self.response_model)

        async def custom_handler(request: Request) -> Response:
            response = await original_handler(request)

            # Pass through anything that isn't a plain JSONResponse:
            # file downloads, redirects, custom Response subclasses.
            if isinstance(response, StreamingResponse):
                return response
            if not isinstance(response, JSONResponse):
                return response

            # Decode the body Pydantic + FastAPI just serialized. The
            # ResponseModel.model_validator has already coerced datetimes
            # to IST at this point.
            try:
                inner = json.loads(response.body.decode("utf-8"))
            except (ValueError, AttributeError):
                return response

            # If the handler explicitly built an envelope (rare — e.g. a
            # special-cased exception handler), don't double-wrap.
            if isinstance(inner, dict) and _ENVELOPE_KEYS <= set(inner.keys()):
                return response

            wrapped = _wrap(inner, hal_type)

            passthrough_headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in _STALE_HEADERS
            }

            return api_response(
                data=wrapped,
                status=response.status_code,
                headers=passthrough_headers or None,
            )

        return custom_handler


def install_hal_route_class(app, *, skip_paths: Optional[Iterable[str]] = None) -> None:
    """Swap every APIRoute on the app to HalApiRoute and re-bake handlers.

    Called from ``main.py`` AFTER all ``include_router`` calls. Routes
    in ``skip_paths`` (typically ``/health`` and ``/ready``) keep their
    original APIRoute behaviour so orchestration probes see plain JSON.

    Safe because HalApiRoute adds no instance attributes — only a method
    override — so ``__class__`` reassignment is a no-op on state.
    """
    skip = set(skip_paths or ())
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if isinstance(route, HalApiRoute):
            continue
        if route.path in skip:
            continue
        route.__class__ = HalApiRoute
        # Re-bake the ASGI entry point so the new get_route_handler wins.
        route.app = request_response(route.get_route_handler())
