"""Pydantic v2 schemas for the divisions catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class DivisionCreateRequest(BaseModel):
    """Body of POST /masters/divisions/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$",
                               description="Lowercase wire code, unique")]
    label: Annotated[str, Field(min_length=1, max_length=255,
                                description="Display label (e.g. 'TMD1', 'Engineering')")]
    requires_other: bool = Field(default=False,
                                 description="If true, the FE shows a free-text 'specify other' input")
    active: bool = Field(default=True)
    email: Annotated[EmailStr, Field(description="Doc 36: contact email (required)")]
    phone_number: Annotated[str, Field(min_length=1, max_length=50,
                                       description="Doc 36: contact phone (required)")]


class DivisionUpdateRequest(BaseModel):
    """Body of PATCH /masters/divisions/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    requires_other: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]
    email: Annotated[Optional[EmailStr], Field(default=None)]
    phone_number: Annotated[Optional[str], Field(default=None, min_length=1, max_length=50)]


class DivisionResponse(ResponseModel):
    """Returned by GET /masters/divisions/list and /details."""

    id: int
    code: str
    label: str
    is_builtin: bool
    requires_other: bool
    active: bool
    email: str
    phone_number: str
    created_at: datetime
    updated_at: datetime
