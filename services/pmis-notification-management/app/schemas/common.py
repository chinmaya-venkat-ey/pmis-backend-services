"""Cross-resource Pydantic helpers (envelopes, pagination)."""
from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorEnvelope(BaseModel):
    """Standard error envelope (matches app/core/response.py:error_envelope)."""

    model_config = ConfigDict(extra="allow")  # request_id is added by the handler

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


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
