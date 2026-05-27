"""Pydantic schemas for SLA Definition APIs — Phase 3."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Create / Update requests
# ---------------------------------------------------------------------------

class SlaCreateRequest(BaseModel):
    dsl: str = Field(..., description="DSL YAML text defining the SLA")
    effective_from: date
    effective_until: Optional[date] = None
    milestone_id: Optional[str] = None   # soft FK to project.milestones.id
    activity_id: Optional[str] = None    # soft FK to project.activities.id
    change_reason: Optional[str] = None


class SlaCreateFromTemplateRequest(BaseModel):
    template_ref: str
    effective_from: date
    effective_until: Optional[date] = None
    milestone_id: Optional[str] = None
    activity_id: Optional[str] = None
    # Top-level DSL key overrides merged before parsing
    overrides: Dict[str, Any] = Field(default_factory=dict)
    change_reason: Optional[str] = None


class SlaUpdateRequest(BaseModel):
    dsl: str = Field(..., description="Updated DSL YAML — creates a new DSL version")
    change_reason: str = Field(..., description="Reason for the change (required for audit)")


# ---------------------------------------------------------------------------
# Sub-table response shapes (nested inside SlaDetailResponse)
# ---------------------------------------------------------------------------

class MetricResponse(BaseModel):
    id: str
    metric_key: str
    display_name: str
    unit: str
    target_numeric: Optional[Decimal]
    target_date: Optional[date]
    direction: str
    is_primary: bool
    model_config = {"from_attributes": True}


class GuardConditionResponse(BaseModel):
    id: str
    metric_key: str
    operator: str
    threshold_value: Decimal
    threshold_unit: Optional[str]
    action: str
    action_description: Optional[str]
    guard_group_id: Optional[int]
    model_config = {"from_attributes": True}


class ConditionBandResponse(BaseModel):
    id: str
    metric_key: str
    band_label: str
    range_min: Optional[Decimal]
    range_max: Optional[Decimal]
    range_unit: Optional[str]
    rate_percent: Optional[Decimal]
    points_contribution: Optional[Decimal]
    fixed_amount: Optional[Decimal]
    sort_order: int
    band_group_id: Optional[int]
    model_config = {"from_attributes": True}


class LookupRowResponse(BaseModel):
    id: str
    lookup_key: str
    lookup_value: Decimal
    sort_order: int
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SLA responses
# ---------------------------------------------------------------------------

class SlaResponse(BaseModel):
    """Flat SLA definition — used in list endpoint."""
    id: str
    project_id: str
    milestone_id: Optional[str]
    activity_id: Optional[str]
    formula_id: str
    formula_type: Optional[str]   # hydrated from formula_library join
    sla_ref: str
    title: str
    description: Optional[str]
    measurement_interval: str
    reporting_interval: str
    baseline_type: str
    compound_metric_rule: str
    ld_aggregation_method: str
    ld_computation_base: str
    status: str
    effective_from: date
    effective_until: Optional[date]
    dsl_version: int
    created_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    model_config = {"from_attributes": True}


class SlaDetailResponse(SlaResponse):
    """Full SLA with all sub-tables — used in get single endpoint."""
    parameters: Dict[str, str] = Field(default_factory=dict)
    metrics: List[MetricResponse] = Field(default_factory=list)
    guard_conditions: List[GuardConditionResponse] = Field(default_factory=list)
    bands: List[ConditionBandResponse] = Field(default_factory=list)
    lookup_table: List[LookupRowResponse] = Field(default_factory=list)
    current_dsl: Optional[str] = None
    current_asl: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Template response
# ---------------------------------------------------------------------------

class TemplateResponse(BaseModel):
    id: str
    template_ref: str
    title: str
    description: Optional[str]
    formula_id: str
    formula_type: Optional[str]
    applicable_to: List[str]
    is_active: bool
    model_config = {"from_attributes": True}
