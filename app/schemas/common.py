"""Cross-resource Pydantic helpers (envelopes, pagination)."""
from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorEnvelope(BaseModel):
    """Standard error inner body (matches ``app/core/response.py:format_error``).

    Wire shape::

        {
          "_type": "Error",
          "errorIdentifier": "<code>",
          "message": "...",
          "_embedded": {"details": {...}}
        }

    This is the inner ``error`` field of the outer ``api_response`` envelope —
    declared here for OpenAPI doc reference only; the handler builds it via
    ``format_error`` (no consumers parse this schema at runtime).
    """

    model_config = ConfigDict(extra="allow")

    type_: str = Field(default="Error", alias="_type")
    errorIdentifier: str
    message: str
    embedded_: dict[str, Any] = Field(default_factory=dict, alias="_embedded")


class HealthResponse(BaseModel):
    """GET /health response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., examples=["ok"])
    service: str = Field(..., examples=["pmis-notification-management"])
    version: str = Field(..., examples=["0.1.0"])


class ReadyResponse(BaseModel):
    """GET /ready response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., examples=["ready"])
    service: str = Field(..., examples=["pmis-notification-management"])
    db: Optional[str] = Field(default=None, description="DB connectivity status: 'ok' or error message")
