"""Pydantic schemas for the planned-resources tab (resource-type phase costing).

Requests accept camelCase (via ``_REQUEST_CONFIG``). The client picks a designation
(``role``) from the leave-management ``/api/designation-rates`` service and passes
that role plus its ``rateCardByYear`` map; the BE derives the per-contract-year
cost, the total months and the summed cost. The client only supplies the role, the
rate card, the deployment window and the quantity.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Dict, Optional

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
    # Designation name + its per-contract-year rate card, from leave-mgmt.
    role: Annotated[str, Field(min_length=1, max_length=255)]
    rate_card_by_year: Dict[str, Decimal]
    # The organisation (masters.vendors.id) the rate card belongs to (optional).
    organisation_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    quantity: Annotated[int, Field(ge=1)] = 1
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None


class PlannedResourceUpdateRequest(BaseModel):
    """PATCH /planned-resources/{id} — partial."""

    model_config = _REQUEST_CONFIG

    role: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    rate_card_by_year: Optional[Dict[str, Decimal]] = None
    organisation_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    quantity: Annotated[Optional[int], Field(default=None, ge=1)]
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None


class PlannedResourceResponse(ResponseModel):
    id: str
    project_id: str
    cost_item_id: str
    role: Optional[str] = None
    vendor_id: Optional[str] = None
    quantity: int
    deploy_start: Optional[date] = None
    deploy_end: Optional[date] = None
    rate_card_snapshot: Optional[Dict[str, Decimal]] = None
    cost_by_year: Optional[Dict[str, Decimal]] = None
    duration_months: Optional[Decimal] = None
    computed_cost: Optional[Decimal] = None
    position: int
    created_at: datetime
    updated_at: datetime
