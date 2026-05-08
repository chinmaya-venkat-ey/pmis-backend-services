"""
Base controller helpers for consistent, centralized API responses.

All helpers return a FastAPI JSONResponse.
Controllers MUST return the Response directly (no tuples).
"""
from typing import Any, Optional
from fastapi.responses import JSONResponse

from .response import api_response


class BaseController:
    """Reusable helpers to produce the standard API envelope.

    This is the ONLY place that should create API responses.
    """

    @staticmethod
    def _envelope(
        *,
        data: Optional[Any] = None,
        message: Optional[Any] = None,
        error: Optional[Any] = None,
        status: int = 200,
    ) -> JSONResponse:
        return api_response(
            data=data,
            message=message,
            error=error,
            status=status,
        )

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
        cls,
        error_payload: Any,
        *,
        status: int,
        message: Optional[str] = None,
    ) -> JSONResponse:
        return cls._envelope(
            data=None,
            message=message,
            error=error_payload,
            status=status,
        )

    @staticmethod
    def stamp_deprecation(
        response: JSONResponse, *, successor_path: str,
    ) -> JSONResponse:
        """Mark a response as deprecated, pointing the FE at the successor.

        Used by the doc-20 legacy catalog endpoints (``/api/v3/divisions``,
        ``/api/v3/resource_types``, ``/api/v3/project_status_transitions``,
        ``/api/v3/vendors/*``) so the FE can detect the deprecation in
        DevTools and migrate at its own pace. Adds two HTTP headers:

          Deprecation: true
          Link: <successor_path>; rel="successor-version"

        The ``Deprecation`` header follows the IETF API Deprecation draft;
        the ``Link`` rel="successor-version" is RFC 8631. Both are widely
        understood by API client libraries and dev tools.

        Returns the same response object so the call composes:
            return BaseController.stamp_deprecation(
                BaseController.ok(data),
                successor_path="/api/v3/master/divisions",
            )
        """
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = (
            f'<{successor_path}>; rel="successor-version"'
        )
        return response