"""FastAPI exception handlers — emit the canonical PMIS envelope.

Failure shape on the wire::

    {
      "data": null,
      "message": null,
      "error": {
        "_type": "Error",
        "errorIdentifier": "<code>",
        "message": "...",
        "_embedded": {"details": {..., "request_id": "..."}}
      },
      "status": <int>
    }

Duplicated across all 4 services — keep in sync.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.response import api_response, format_error
from app.utilities.logger import get_logger


logger = get_logger("pmis.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _details_with_request_id(details, request: Request) -> dict:
    merged = dict(details) if details else {}
    merged.setdefault("request_id", _request_id(request))
    return merged


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return api_response(
            status=exc.status_code,
            error=format_error(
                exc.code,
                exc.message,
                _details_with_request_id(exc.details, request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return api_response(
            status=exc.status_code,
            error=format_error(
                "HTTP_ERROR",
                str(exc.detail),
                _details_with_request_id({}, request),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = jsonable_encoder(
            exc.errors(),
            custom_encoder={ValueError: lambda v: str(v)},
        )
        for item in errors:
            item.pop("url", None)
        return api_response(
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error=format_error(
                "VALIDATION_ERROR",
                "Validation failed",
                _details_with_request_id({"errors": errors}, request),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return api_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=format_error(
                "INTERNAL_SERVER_ERROR",
                "Internal server error",
                _details_with_request_id({}, request),
            ),
        )
