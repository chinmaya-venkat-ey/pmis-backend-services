"""Schemas for NpqpService responses (Phase C)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class NpqpResourceCost(BaseModel):
    """One row of the F/PA breakdown — a PLANNED allocation (by designation,
    from project.activity_planned_resources) or an ACTUAL per-resource monthly
    cost (from leave-mgmt)."""
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
        description="F — Planned Quarterly Payment (RFP §5.28.1.d.c). Sum of "
                    "computed_cost (quantity × monthly_rate × duration) over the "
                    "project.activity_planned_resources allocations whose "
                    "planned_deployment_date falls in the project-anchored quarter "
                    "— the same per-activity plan the finance page shows.",
    )
    pa_amount: Decimal = Field(
        default=Decimal("0"),
        serialization_alias="paAmount",
        description="PA — Payable amount for Actual resource deployment "
                    "(RFP §5.28.1.d.g) = F (the activity plan) prorated by the "
                    "project's attendance ratio from leave-mgmt (Σ actual cost ÷ "
                    "Σ planned rate, clamped to [0,1]). leave-mgmt folds in "
                    "attendance/paid-leave/half-day/§5.24.1 relaxation; because the "
                    "leave roster is a different resource set than the plan, it is "
                    "used as an attendance FACTOR against F, not an absolute cost — "
                    "so PA ≤ F and reconciles with finance. LD is on PQP (=F), "
                    "deducted from PA.",
    )
    qgr_amount: Decimal = Field(
        default=Decimal("0"),
        serialization_alias="qgrAmount",
        description="Quarterly Guaranteed Revenue (RFP §5.23.2). "
                    "Present only if project_qgr_config has an effective row.",
    )
    npqp: Decimal = Field(
        description=(
            "F + QGR — DELETED-CLAUSE reference only. RFP §5.28.1.d.e (NPQP) was "
            "DELETED by the corrigendum; NPQP is NOT the LD base. LD is charged on "
            "PQP (= F); QGR is added back only in AQP = (PA − LD) + QGR. Kept for "
            "display/audit; do not compute penalties from it."
        )
    )
    status: str = Field(
        description="'ok' | 'leave_mgmt_unavailable' | 'no_resources' | "
                    "'no_deployment_plan'. Settlement close blocks (marks "
                    "blocked_missing_npqp) when != ok.",
    )
    per_month: List[NpqpResourceCost] = Field(
        default_factory=list, serialization_alias="perMonth",
        description="Audit trail — every row that contributed to F.",
    )

    model_config = {"populate_by_name": True}
