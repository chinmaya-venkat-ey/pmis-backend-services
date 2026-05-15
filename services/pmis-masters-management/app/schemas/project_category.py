"""Pydantic v2 schemas for the project_categories catalog (doc 37)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCategoryCreateRequest(BaseModel):
    """Body of POST /masters/project-categories/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]
    label: Annotated[str, Field(min_length=1, max_length=255)]
    requires_other: bool = Field(default=False)
    active: bool = Field(default=True)
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class ProjectCategoryUpdateRequest(BaseModel):
    """Body of PATCH /masters/project-categories/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    requires_other: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class ProjectCategoryResponse(BaseModel):
    """Returned by GET /masters/project-categories/list and /details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: str
    is_builtin: bool
    requires_other: bool
    active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
