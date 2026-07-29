"""Pydantic schemas for the planned-resources tab (resource-type phase costing).

Requests accept camelCase (via ``_REQUEST_CONFIG``); the rate, months and cost are
BE-derived (monthly rate snapshotted from the designation master, months from the
deployment window) — the client only supplies the designation, deployment window
and quantity.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel

_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class PlannedResourceCreateRequest(BaseModel):
    """POST /projects/{uuid}/planned-resources."""

    model_config = _REQUEST_CONFIG

    # The resource_cost cost row this planned resource rolls up into.
    cost_item_id: Annotated[str, Field(min_length=1, max_length=36)]
    designation_id: Annotated[str, Field(min_length=1, max_length=36)]
    quantity: Annotated[int, Field(ge=1)] = 1
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None


class PlannedResourceUpdateRequest(BaseModel):
    """PATCH /planned-resources/{id} — partial."""

    model_config = _REQUEST_CONFIG

    designation_id: Annotated[Optional[str], Field(default=None, min_length=1, max_length=36)]
    quantity: Annotated[Optional[int], Field(default=None, ge=1)]
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None


class PlannedResourceResponse(ResponseModel):
    id: str
    project_id: str
    cost_item_id: str
    designation_id: str
    vendor_id: Optional[str] = None
    quantity: int
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None
    monthly_rate_snapshot: Optional[Decimal] = None
    duration_months: Optional[Decimal] = None
    computed_cost: Optional[Decimal] = None
    position: int
    created_at: datetime
    updated_at: datetime
