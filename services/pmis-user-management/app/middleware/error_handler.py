"""FastAPI exception handlers — CANONICAL declaration site.

Translates DomainError → status_code + JSON envelope, plus Pydantic
validation errors, StarletteHTTPException, and bare Exception fallbacks.

WARNING: Duplicated across services. Keep in sync.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError, TwoFactorRequiredError
from app.core.response import error_envelope
from app.utilities.logger import get_logger


logger = get_logger("pmis.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(TwoFactorRequiredError)
    async def two_factor_handler(request: Request, exc: TwoFactorRequiredError):
        # Special: 2FA signal is a 200 with a special body, not an error.
        return JSONResponse(
            status_code=200,
            content={
                "requires_otp": True,
                "ephemeral_token": exc.details["ephemeral_token"],
                "channels_available": exc.details["channels_available"],
            },
        )

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
