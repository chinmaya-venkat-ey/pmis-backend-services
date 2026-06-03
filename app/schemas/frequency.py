"""Pydantic v2 schemas for the frequencies catalog.

Code is lowercased server-side (e.g. "Monthly" → "monthly").
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas._base import ResponseModel


class FrequencyCreateRequest(BaseModel):
    """Body of POST /master/frequencies/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$",
                               description="Code (normalized to lowercase server-side)")]
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    position: Annotated[int, Field(default=0, ge=0, description="Display ordering")]

    @field_validator("code")
    @classmethod
    def lowercase_code(cls, v: str) -> str:
        return v.lower()


class FrequencyUpdateRequest(BaseModel):
    """Body of PATCH /master/frequencies/{code} — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=64)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    position: Annotated[Optional[int], Field(default=None, ge=0)]
    active: Annotated[Optional[bool], Field(default=None)]


class FrequencyResponse(ResponseModel):
    """Returned by GET /master/frequencies and /{code}."""

    id: str
    code: str
    name: str
    description: Optional[str] = None
    position: int
    is_builtin: bool
    active: bool
    created_at: datetime
    updated_at: datetime
