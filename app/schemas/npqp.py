"""Schemas for NpqpService responses (Phase C)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class NpqpResourceCost(BaseModel):
    """One resource's contribution to F for one month of the quarter."""
    resource_id: str = Field(serialization_alias="resourceId")
    employee_name: Optional[str] = Field(default=None, serialization_alias="employeeName")
    year: int
    month: int
    monthly_rate: Optional[Decimal] = Field(default=None, serialization_alias="monthlyRate")
    cost: Decimal


class NpqpResponse(BaseModel):
    """Full NPQP breakdown for one project × one quarter."""
    project_id: str = Field(serialization_alias="projectId")
    fiscal_year: int = Field(serialization_alias="fiscalYear")
    quarter: int
    quarter_start: date = Field(serialization_alias="quarterStart")
    quarter_end: date = Field(serialization_alias="quarterEnd")
    f_amount: Decimal = Field(
        serialization_alias="fAmount",
        description="Planned/actual quarterly staff cost — sum of per-resource "
                    "per-month costs from leave-mgmt.",
    )
    qgr_amount: Decimal = Field(
        default=Decimal("0"),
        serialization_alias="qgrAmount",
        description="Quarterly Guaranteed Revenue (RFP §5.23.2). "
                    "Present only if project_qgr_config has an effective row.",
    )
    npqp: Decimal = Field(description="F + QGR")
    status: str = Field(
        description="'ok' | 'leave_mgmt_unavailable' | 'no_resources'. "
                    "Settlement close blocks (marks blocked_missing_npqp) when != ok.",
    )
    per_month: List[NpqpResourceCost] = Field(
        default_factory=list, serialization_alias="perMonth",
        description="Audit trail — every row that contributed to F.",
    )

    model_config = {"populate_by_name": True}
