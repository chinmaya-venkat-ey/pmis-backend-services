"""Pydantic schemas for SLA-Activity mapping CRUD."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# Override keys recognised by the evaluator. The SLA template's
# `placeholders` array declares which of these (or other keys) the
# operator must fill in when attaching to an activity; these are the
# names the evaluator looks up on mapping.overrides.
WELL_KNOWN_OVERRIDE_KEYS = {
    "t_anchor_date",        # ISO date string, concrete value of SLA's T anchor
    "actual_start_date",    # ISO date string
    "actual_end_date",      # ISO date string
    "ld_base_amount",       # numeric, INR base for LD calc
    "severity_profile_id",  # uuid, overrides project's severity profile
    "approval_date_K",      # ISO date — PMU-SLA008 K (UIDAI approval)
    "notification_date",    # ISO date — PMU-SLA009 (date UIDAI notified)
}


class SlaActivityMappingCreateRequest(BaseModel):
    activity_id: str = Field(..., max_length=36)
    sla_id: str = Field(..., max_length=36)
    effective_from: date
    effective_until: Optional[date] = None
    overrides: Dict[str, Any] = Field(default_factory=dict)


class SlaActivityMappingUpdateRequest(BaseModel):
    effective_until: Optional[date] = None
    status: Optional[str] = Field(None, pattern=r"^(ACTIVE|INACTIVE|RETIRED)$")
    overrides: Optional[Dict[str, Any]] = None


class SlaActivityMappingResponse(BaseModel):
    id: str
    activity_id: str
    sla_id: str
    sla_ref: str
    sla_title: str
    contract_type: Optional[str] = None
    formula_type: Optional[str] = None
    category: Optional[str] = None
    overrides: Dict[str, Any] = Field(default_factory=dict)
    status: str
    effective_from: date
    effective_until: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
