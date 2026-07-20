"""Pydantic schemas for the sla_quarterly_aggregate API responses."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class QuarterlyAggregateItem(BaseModel):
    """One (mapping, quarter) rollup row."""
    id: str
    mapping_id: str = Field(serialization_alias="mappingId")
    sla_id: str = Field(serialization_alias="slaId")
    sla_ref: Optional[str] = Field(default=None, serialization_alias="slaRef")
    project_id: str = Field(serialization_alias="projectId")
    activity_id: str = Field(serialization_alias="activityId")
    fiscal_year: int = Field(serialization_alias="fiscalYear")
    quarter: int
    quarter_start: date = Field(serialization_alias="quarterStart")
    quarter_end: date = Field(serialization_alias="quarterEnd")
    accumulated_points: Optional[Decimal] = Field(
        default=None, serialization_alias="accumulatedPoints",
    )
    derived_severity: Optional[int] = Field(
        default=None, serialization_alias="derivedSeverity",
    )
    ld_percent: Optional[Decimal] = Field(
        default=None, serialization_alias="ldPercent",
    )
    carried_forward: bool = Field(serialization_alias="carriedForward")
    source_result_ids: Optional[List[str]] = Field(
        default=None, serialization_alias="sourceResultIds",
    )
    notes: Optional[dict] = None
    computed_at: datetime = Field(serialization_alias="computedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class QuarterlyAggregateResponse(BaseModel):
    """Response envelope for ``GET /projects/{id}/quarterly-aggregate?quarter=...``."""
    project_id: str = Field(serialization_alias="projectId")
    quarter_key: str = Field(serialization_alias="quarterKey")
    fiscal_year: int = Field(serialization_alias="fiscalYear")
    quarter: int
    quarter_start: date = Field(serialization_alias="quarterStart")
    quarter_end: date = Field(serialization_alias="quarterEnd")
    total_ld_percent_uncapped: Decimal = Field(
        serialization_alias="totalLdPercentUncapped",
        description="Sum of per-mapping ld_percent, BEFORE the 10% quarter cap.",
    )
    items: List[QuarterlyAggregateItem]

    model_config = {"populate_by_name": True}
