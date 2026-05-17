"""Pydantic v2 schemas for the priorities catalog (doc 41).

Code is uppercased server-side (e.g. "p1" → "P1").
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas._base import ResponseModel


class PriorityCreateRequest(BaseModel):
    """Body of POST /masters/priorities/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=16, pattern=r"^[a-zA-Z0-9_-]+$",
                               description="Code (normalized to UPPERCASE server-side)")]
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    position: Annotated[int, Field(default=0, ge=0, description="Display ordering; lower = higher priority")]

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper()


class PriorityUpdateRequest(BaseModel):
    """Body of PATCH /masters/priorities/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=64)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    position: Annotated[Optional[int], Field(default=None, ge=0)]
    active: Annotated[Optional[bool], Field(default=None)]


class PriorityResponse(ResponseModel):
    """Returned by GET /masters/priorities/list and /details."""

    id: str
    code: str
    name: str
    description: Optional[str] = None
    position: int
    is_builtin: bool
    active: bool
    created_at: datetime
    updated_at: datetime
