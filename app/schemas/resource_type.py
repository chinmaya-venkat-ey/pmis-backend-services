"""Pydantic v2 schemas for the resource_types catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._base import ResponseModel


class ResourceTypeCreateRequest(BaseModel):
    """Body of POST /masters/resource-types/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    active: bool = Field(default=True)


class ResourceTypeUpdateRequest(BaseModel):
    """Body of PATCH /masters/resource-types/{rt_id}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    active: Annotated[Optional[bool], Field(default=None)]


class ResourceTypeResponse(ResponseModel):
    """Returned by GET /masters/resource-types/list and /details."""

    id: str
    code: str
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime
