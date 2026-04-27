"""Base controller helpers — consistent API envelope for every route.

Ported verbatim from the monolith so response shapes match across
services.
"""
from typing import Any, Optional

from fastapi.responses import JSONResponse

from .response import api_response


class BaseController:
    @staticmethod
    def _envelope(
        *,
        data: Optional[Any] = None,
        message: Optional[Any] = None,
        error: Optional[Any] = None,
        status: int = 200,
    ) -> JSONResponse:
        return api_response(data=data, message=message, error=error, status=status)

    @classmethod
    def ok(cls, data: Any, message: Optional[str] = None) -> JSONResponse:
        return cls._envelope(data=data, message=message, status=200)

    @classmethod
    def created(cls, data: Any, message: Optional[str] = None) -> JSONResponse:
        return cls._envelope(data=data, message=message, status=201)

    @classmethod
    def no_content(cls, message: Optional[str] = None) -> JSONResponse:
        return cls._envelope(data=None, message=message, status=204)

    @classmethod
    def error(
        cls, error_payload: Any, *, status: int, message: Optional[str] = None,
    ) -> JSONResponse:
        return cls._envelope(
            data=None, message=message, error=error_payload, status=status,
        )
