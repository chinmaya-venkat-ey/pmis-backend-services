"""Register FastAPI exception handlers.

Translates:
  - DomainError subclasses → status_code + structured error envelope
  - StarletteHTTPException → wrapped error envelope
  - RequestValidationError → 422 with structured details
  - Bare Exception → 500 (logged)

All responses include the X-Request-ID for correlation.

Ported and extended from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\middleware\\error_handler.py:1-63
adding the DomainError handler that wasn't in the source.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.response import error_envelope
from app.utilities.logger import get_logger


logger = get_logger("pmis.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                **error_envelope(exc.code, exc.message, exc.details),
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Preserve raw HTTPException callers (rare — should mostly be DomainError)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                **error_envelope("HTTP_ERROR", str(exc.detail), {}),
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Pydantic v2 errors can carry raw Python objects in `ctx`. Coerce
        # via jsonable_encoder and strip the docs `url` field.
        raw = exc.errors()
        details = jsonable_encoder(
            raw,
            custom_encoder={ValueError: lambda v: str(v)},
        )
        for item in details:
            item.pop("url", None)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                **error_envelope("VALIDATION_ERROR", "Validation failed", {"errors": details}),
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                **error_envelope("INTERNAL_SERVER_ERROR", "Internal server error", {}),
                "request_id": _request_id(request),
            },
        )
