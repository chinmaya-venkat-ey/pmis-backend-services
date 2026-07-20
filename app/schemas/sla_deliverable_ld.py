"""Track A (per-deliverable) LD summary per activity.

Consumed by project-mgmt's payment page to show LD deductions on the
deliverable's own cost item, per RFP §5.28.2.b/c — separate from the
quarterly settlement (§5.28.3 / §5.27.6) which handles Track B.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class DeliverableLdItem(BaseModel):
    """One Track A LD row — a per-mapping evaluation on this activity."""
    mapping_id: str = Field(serialization_alias="mappingId")
    sla_id: str = Field(serialization_alias="slaId")
    sla_ref: Optional[str] = Field(default=None, serialization_alias="slaRef")
    ld_formula_rule: str = Field(serialization_alias="ldFormulaRule")
    ld_percent: Optional[Decimal] = Field(default=None, serialization_alias="ldPercent")
    ld_amount: Optional[Decimal] = Field(
        default=None, serialization_alias="ldAmount",
        description="Rupee amount. Computed = ld_percent × ld_base_amount (deliverable cost).",
    )
    ld_base_amount: Optional[Decimal] = Field(
        default=None, serialization_alias="ldBaseAmount",
        description="Deliverable cost — read from sla_activity_mappings.overrides.ld_base_amount.",
    )
    observed_value: Optional[Decimal] = Field(
        default=None, serialization_alias="observedValue",
        description="e.g. weeks_of_delay for SLA 001/002.",
    )
    evaluated_on: Optional[date] = Field(default=None, serialization_alias="evaluatedOn")
    status: Optional[str] = None
    note: Optional[str] = None


class DeliverableLdResponse(BaseModel):
    """Envelope for GET /sla-compliance/activities/{id}/deliverable-lds."""
    activity_id: str = Field(serialization_alias="activityId")
    total_ld_amount: Decimal = Field(
        serialization_alias="totalLdAmount",
        description="Sum of ldAmount across all items — the aggregate "
                    "deduction to bill on the deliverable's invoice.",
    )
    items: List[DeliverableLdItem]

    model_config = {"populate_by_name": True}
