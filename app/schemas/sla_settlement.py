"""Pydantic schemas for the sla_settlement_period API (Phase D)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SettlementItem(BaseModel):
    """One settlement row — the quarter-close artifact per RFP §5.28.1.d.h."""
    id: str
    project_id: str = Field(serialization_alias="projectId")
    contract_type: Optional[str] = Field(default=None, serialization_alias="contractType")
    fiscal_year: int = Field(serialization_alias="fiscalYear")
    quarter: int
    quarter_start: date = Field(serialization_alias="quarterStart")
    quarter_end: date = Field(serialization_alias="quarterEnd")
    sum_ld_percent: Optional[Decimal] = Field(default=None, serialization_alias="sumLdPercent")
    capped_ld_percent: Optional[Decimal] = Field(default=None, serialization_alias="cappedLdPercent")
    f_amount: Optional[Decimal] = Field(default=None, serialization_alias="fAmount")
    qgr_amount: Optional[Decimal] = Field(default=None, serialization_alias="qgrAmount")
    npqp: Optional[Decimal] = None
    ld_amount: Optional[Decimal] = Field(default=None, serialization_alias="ldAmount")
    pa_amount: Optional[Decimal] = Field(default=None, serialization_alias="paAmount")
    aqp_amount: Optional[Decimal] = Field(default=None, serialization_alias="aqpAmount")
    status: str
    closed_at: Optional[datetime] = Field(default=None, serialization_alias="closedAt")
    closed_by: Optional[str] = Field(default=None, serialization_alias="closedBy")
    override_reason: Optional[str] = Field(default=None, serialization_alias="overrideReason")
    source_aggregate_ids: Optional[List[str]] = Field(
        default=None, serialization_alias="sourceAggregateIds",
    )
    consequence_flags: Dict[str, Any] = Field(
        default_factory=dict, serialization_alias="consequenceFlags",
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class SettlementListResponse(BaseModel):
    project_id: str = Field(serialization_alias="projectId")
    items: List[SettlementItem]

    model_config = {"populate_by_name": True}


class SettlementOverrideRequest(BaseModel):
    """POST body for `/settlement/{quarter}/override` — finance role only."""
    sum_ld_percent: Decimal = Field(
        ge=0,
        alias="sumLdPercent",
        description="New sum-of-per-SLA-LD-% value. Will be re-capped at "
                    "10% × NPQP per RFP §5.27.6 before persistence.",
    )
    override_reason: str = Field(
        min_length=1,
        alias="overrideReason",
        description="Free text — audit trail. Required.",
    )

    model_config = {"populate_by_name": True}
