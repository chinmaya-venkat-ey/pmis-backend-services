"""FastAPI exception handlers — emit the canonical PMIS envelope."""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.response import api_response, format_error
from app.utilities.logger import get_logger


logger = get_logger("pmis.errors")


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return api_response(
            status=exc.status_code,
            error=format_error(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return api_response(
            status=exc.status_code,
            error=format_error("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = jsonable_encoder(
            exc.errors(),
            custom_encoder={ValueError: lambda v: str(v)},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return api_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=format_error("internal_server_error", "Internal server error"),
        )
