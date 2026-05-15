"""FastAPI exception handlers for pmis-project-management.

Duplicated from services/pmis-user-management/app/middleware/error_handler.py
minus the TwoFactor handler (only user-svc raises that).
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
        return JSONResponse(
            status_code=exc.status_code,
            content={
                **error_envelope("HTTP_ERROR", str(exc.detail), {}),
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details = jsonable_encoder(
            exc.errors(),
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
