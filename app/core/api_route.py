"""HalApiRoute — auto-wraps successful responses in the PMIS envelope.

Duplicated from project-management. Keep in sync across all PMIS services.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from app.core.response import api_response, hal_collection, hal_resource


_ENVELOPE_KEYS = frozenset({"data", "message", "error", "status"})
_STALE_HEADERS = frozenset({"content-length", "content-type"})
_KEEP_KEYS = frozenset({"_type", "_links", "_embedded", "data", "message", "error", "status"})


def _to_camel(name: str) -> str:
    if "_" not in name:
        return name
    leading = ""
    body = name
    while body.startswith("_"):
        leading += "_"
        body = body[1:]
    if not body:
        return name
    parts = body.split("_")
    head = parts[0]
    tail = "".join(p.title() for p in parts[1:])
    return f"{leading}{head}{tail}"


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            new_k = k if k in _KEEP_KEYS else _to_camel(k)
            out[new_k] = _camelize(v)
        return out
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def _hal_type_from_model(response_model: Any) -> str:
    if response_model is None:
        return "Resource"
    name = getattr(response_model, "__name__", "") or ""
    # Strip "Response" suffix if present (e.g. FileObjectResponse -> FileObject)
    if name.endswith("Response"):
        name = name[: -len("Response")]
    return name or "Resource"


class HalApiRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def _wrapped(request: Request) -> Response:
            response = await original(request)

            if isinstance(response, StreamingResponse):
                return response
            if not isinstance(response, JSONResponse):
                return response

            body = json.loads(response.body)

            # Already wrapped (e.g. handler called api_response directly).
            if isinstance(body, dict) and _ENVELOPE_KEYS <= body.keys():
                return response

            # _bare=True: handler built its own collection/resource dict —
            # camelize keys and wrap in the outer envelope only.
            if isinstance(body, dict) and body.get("_bare"):
                body.pop("_bare", None)
                camelized = _camelize(body)
                return api_response(data=camelized, status=response.status_code)

            # Determine _type from route's response_model.
            hal_type = _hal_type_from_model(self.response_model)
            # Hydrate _links.self using route path.
            self_href = str(request.url.path)

            camelized = _camelize(body)

            if isinstance(body, dict):
                wrapped = hal_resource(hal_type, camelized, self_link=self_href)
            elif isinstance(body, list):
                wrapped = hal_collection(
                    camelized, total=len(camelized),
                    self_link=self_href,
                )
            else:
                wrapped = camelized

            # Carry over non-content headers.
            extra_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in _STALE_HEADERS
            }
            return api_response(
                data=wrapped,
                status=response.status_code,
                headers=extra_headers or None,
            )

        return _wrapped


def install_hal_route_class(
    app: Any,
    skip_paths: Optional[Iterable[str]] = None,
) -> None:
    skip = set(skip_paths or [])
    for route in app.routes:
        if hasattr(route, "path") and route.path in skip:
            continue
        if isinstance(route, APIRoute) and not isinstance(route, HalApiRoute):
            route.__class__ = HalApiRoute
