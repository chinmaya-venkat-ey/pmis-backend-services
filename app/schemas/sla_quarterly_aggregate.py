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
    ld_formula_rule: Optional[str] = Field(
        default=None, serialization_alias="ldFormulaRule",
        description="Track classifier — populated from sla_definitions. "
                    "Track B (LADDER / PER_UNIT_TIME_QUARTERLY / PER_OCCURRENCE "
                    "/ AVAILABILITY_UPTIME / DAYS_WEIGHTED) participates in "
                    "the quarterly settlement's 10% cap. Track A "
                    "(PER_UNIT_TIME_DELIVERABLE) is billed on the "
                    "deliverable's own invoice via the payment page's per-cost-item "
                    "block, NOT this settlement.",
    )
    ld_track: Optional[str] = Field(
        default=None, serialization_alias="ldTrack",
        description="'B' when the rule participates in the NPQP-quarter "
                    "settlement, 'A' for per-deliverable rules, None when "
                    "the rule isn't classified.",
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
        description=(
            "Σ of ONE %LD per SLA (each SLA's worst across its per-mapping rows, "
            "RFP §5.28.1.d.f), BEFORE the 10% quarter cap. Matches the settlement's "
            "sumLdPercent (collapsed per SLA); it is NOT a raw per-mapping sum."
        ),
    )
    items: List[QuarterlyAggregateItem]

    model_config = {"populate_by_name": True}
