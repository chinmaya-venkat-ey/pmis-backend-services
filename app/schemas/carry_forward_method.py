"""Pydantic v2 schemas for the carry-forward-methods catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas._base import ResponseModel


class CarryForwardMethodCreateRequest(BaseModel):
    """Body of POST /master/carry-forward-methods/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$",
                               description="Code (normalized to lowercase server-side)")]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    method: Annotated[str, Field(min_length=1, max_length=16, description="milestone | phase | time")]
    variant: Annotated[str, Field(min_length=1, max_length=16, description="evenly | custom | monthly | …")]
    formula: Annotated[str, Field(min_length=1, max_length=500,
                                  description="Arithmetic expression over the recipient variable set")]
    position: Annotated[int, Field(default=0, ge=0)]

    @field_validator("code")
    @classmethod
    def lowercase_code(cls, v: str) -> str:
        return v.lower()


class CarryForwardMethodUpdateRequest(BaseModel):
    """Body of PATCH /master/carry-forward-methods/{code} — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=80)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]
    method: Annotated[Optional[str], Field(default=None, min_length=1, max_length=16)]
    variant: Annotated[Optional[str], Field(default=None, min_length=1, max_length=16)]
    formula: Annotated[Optional[str], Field(default=None, min_length=1, max_length=500)]
    position: Annotated[Optional[int], Field(default=None, ge=0)]
    active: Annotated[Optional[bool], Field(default=None)]


class CarryForwardMethodResponse(ResponseModel):
    """Returned by GET /master/carry-forward-methods and /{code}."""

    id: str
    code: str
    name: str
    description: Optional[str] = None
    method: str
    variant: str
    formula: str
    position: int
    is_builtin: bool
    active: bool
    created_at: datetime
    updated_at: datetime
