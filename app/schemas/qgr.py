"""Pydantic schemas for project.project_qgr_config CRUD.

RFP §5.23.2 QGR — Quarterly Guaranteed Revenue, defined per project ×
phase (Phase 1 originates it; Phase 2/3 quarters continue to add it to
NPQP per the RFP §5.28.1.d worked example).

Effective-dated rows: adding a new row supersedes the older one from
``effective_from`` onwards. Historical rows are kept so past quarters
settle at the QGR that was actually in force.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ProjectQgrConfigItem(BaseModel):
    id: str
    project_id: str = Field(serialization_alias="projectId")
    phase: str
    qgr_amount_per_quarter: Decimal = Field(serialization_alias="qgrAmountPerQuarter")
    effective_from: date = Field(serialization_alias="effectiveFrom")
    effective_until: Optional[date] = Field(default=None, serialization_alias="effectiveUntil")
    notes: Optional[str] = None
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ProjectQgrConfigCreate(BaseModel):
    """Body for POST — add a new effective-dated QGR row."""
    phase: str = Field(
        description="Contract phase this QGR applies to. Values follow the "
                    "contract_phase_config classifier: 'PHASE_1' (RFP §5.23.2), "
                    "'PHASE_2_3', 'GOVERNANCE_TOOL', 'NONE'.",
    )
    qgr_amount_per_quarter: Decimal = Field(
        ge=0,
        serialization_alias="qgrAmountPerQuarter",
        description="Rupees per quarter, exclusive of taxes. Added to F when "
                    "NpqpService computes NPQP for a quarter whose end date "
                    "falls in [effective_from, effective_until].",
    )
    effective_from: date = Field(serialization_alias="effectiveFrom")
    effective_until: Optional[date] = Field(default=None, serialization_alias="effectiveUntil")
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}


class ProjectQgrConfigList(BaseModel):
    project_id: str = Field(serialization_alias="projectId")
    items: List[ProjectQgrConfigItem]

    model_config = {"populate_by_name": True}
