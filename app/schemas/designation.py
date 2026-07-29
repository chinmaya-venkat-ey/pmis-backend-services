"""Pydantic v2 schemas for the designations catalog."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._base import ResponseModel


class DesignationCreateRequest(BaseModel):
    """Body of POST /masters/designations/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    # The organization this designation belongs to (masters.vendors.id). NULL =
    # a global/template designation shared across orgs.
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    # Per-month rate used to cost planned resources.
    monthly_rate: Annotated[Optional[Decimal], Field(default=None, ge=0)]
    active: bool = Field(default=True)


class DesignationUpdateRequest(BaseModel):
    """Body of PATCH /masters/designations/{designation_id} — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    monthly_rate: Annotated[Optional[Decimal], Field(default=None, ge=0)]
    active: Annotated[Optional[bool], Field(default=None)]


class DesignationResponse(ResponseModel):
    """Returned by GET /masters/designations and /designations/{id}."""

    id: str
    code: str
    name: str
    vendor_id: Optional[str] = None
    monthly_rate: Optional[Decimal] = None
    active: bool
    created_at: datetime
    updated_at: datetime
