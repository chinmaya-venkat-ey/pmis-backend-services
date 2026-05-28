"""Pydantic schemas for SLA master onboarding."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-table inputs
# ---------------------------------------------------------------------------

class SlaMetricInput(BaseModel):
    metric_key: str = Field(..., max_length=100)
    display_name: str = Field(..., max_length=255)
    unit: str = Field("", max_length=50)
    target_numeric: Optional[Decimal] = None
    target_date: Optional[date] = None
    direction: str = Field("LOWER_BETTER", pattern=r"^(LOWER_BETTER|HIGHER_BETTER)$")
    is_primary: bool = True


class SlaParameterInput(BaseModel):
    param_key: str = Field(..., max_length=100)
    param_value: str = Field(..., max_length=1000)


class SlaConditionBandInput(BaseModel):
    metric_key: str = Field(..., max_length=100)
    band_label: str = Field(..., max_length=50)
    range_min: Optional[Decimal] = None
    range_max: Optional[Decimal] = None
    range_unit: Optional[str] = Field(None, max_length=30)
    severity_level: Optional[int] = None
    rate_percent: Optional[Decimal] = None
    points_contribution: Optional[Decimal] = None
    fixed_amount: Optional[Decimal] = None
    band_group_id: Optional[int] = None
    sort_order: int = 0


class SlaLookupRowInput(BaseModel):
    lookup_key: str = Field(..., max_length=200)
    lookup_value: Decimal
    sort_order: int = 0


class SlaGuardConditionInput(BaseModel):
    metric_key: str = Field(..., max_length=100)
    operator: str = Field(..., pattern=r"^(LT|LTE|GT|GTE|EQ|NEQ)$")
    threshold_value: Decimal
    threshold_unit: Optional[str] = Field(None, max_length=30)
    action: str = Field(..., pattern=r"^(EXCLUDE|SUSPEND|PROBATION)$")
    action_description: Optional[str] = None
    guard_group_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Main onboard request
# ---------------------------------------------------------------------------

class SlaOnboardRequest(BaseModel):
    contract_type: str = Field(..., max_length=20, pattern=r"^(BSP|MSAP|MSIP|PMU)$")
    formula_type: str = Field(
        ...,
        pattern=r"^(band_accumulation|point_accumulation|fixed_escalation|wac)$",
    )
    sla_ref: str = Field(..., max_length=50, pattern=r"^[A-Z0-9_-]+$")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    measurement_interval: str = Field(
        "MONTHLY", pattern=r"^(DAILY|WEEKLY|MONTHLY|QUARTERLY|ONE_TIME)$"
    )
    reporting_interval: str = Field(
        "QUARTERLY", pattern=r"^(WEEKLY|MONTHLY|QUARTERLY|ANNUAL)$"
    )
    baseline_type: str = Field("STATIC", pattern=r"^(STATIC|ROLLING)$")
    compound_metric_rule: str = Field(
        "INDEPENDENT", pattern=r"^(INDEPENDENT|COMBINED)$"
    )
    ld_aggregation_method: str = Field("SUM", pattern=r"^(SUM|MAX|WEIGHTED)$")
    ld_computation_base: str = Field(
        "QUARTERLY_PAYMENT",
        pattern=r"^(QUARTERLY_PAYMENT|ANNUAL_PAYMENT|FIXED_AMOUNT)$",
    )
    effective_from: date
    effective_until: Optional[date] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[SlaMetricInput] = Field(..., min_length=1)
    parameters: List[SlaParameterInput] = Field(default_factory=list)
    condition_bands: List[SlaConditionBandInput] = Field(default_factory=list)
    lookup_table: List[SlaLookupRowInput] = Field(default_factory=list)
    guard_conditions: List[SlaGuardConditionInput] = Field(default_factory=list)


class SlaUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    measurement_interval: Optional[str] = Field(
        None, pattern=r"^(DAILY|WEEKLY|MONTHLY|QUARTERLY|ONE_TIME)$"
    )
    reporting_interval: Optional[str] = Field(
        None, pattern=r"^(WEEKLY|MONTHLY|QUARTERLY|ANNUAL)$"
    )
    baseline_type: Optional[str] = Field(None, pattern=r"^(STATIC|ROLLING)$")
    compound_metric_rule: Optional[str] = Field(
        None, pattern=r"^(INDEPENDENT|COMBINED)$"
    )
    ld_aggregation_method: Optional[str] = Field(None, pattern=r"^(SUM|MAX|WEIGHTED)$")
    ld_computation_base: Optional[str] = Field(
        None, pattern=r"^(QUARTERLY_PAYMENT|ANNUAL_PAYMENT|FIXED_AMOUNT)$"
    )
    effective_until: Optional[date] = None
    status: Optional[str] = Field(None, pattern=r"^(ACTIVE|INACTIVE)$")
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Sub-table responses
# ---------------------------------------------------------------------------

class SlaMetricResponse(BaseModel):
    id: str
    sla_id: str
    metric_key: str
    display_name: str
    unit: str
    target_numeric: Optional[Decimal] = None
    target_date: Optional[date] = None
    direction: str
    is_primary: bool
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SlaParameterResponse(BaseModel):
    id: str
    sla_id: str
    param_key: str
    param_value: str
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SlaConditionBandResponse(BaseModel):
    id: str
    sla_id: str
    metric_key: str
    band_label: str
    range_min: Optional[Decimal] = None
    range_max: Optional[Decimal] = None
    range_unit: Optional[str] = None
    severity_level: Optional[int] = None
    rate_percent: Optional[Decimal] = None
    points_contribution: Optional[Decimal] = None
    fixed_amount: Optional[Decimal] = None
    band_group_id: Optional[int] = None
    sort_order: int
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SlaLookupRowResponse(BaseModel):
    id: str
    sla_id: str
    lookup_key: str
    lookup_value: Decimal
    sort_order: int
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SlaGuardConditionResponse(BaseModel):
    id: str
    sla_id: str
    metric_key: str
    operator: str
    threshold_value: Decimal
    threshold_unit: Optional[str] = None
    action: str
    action_description: Optional[str] = None
    guard_group_id: Optional[int] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Definition responses
# ---------------------------------------------------------------------------

class SlaDefinitionResponse(BaseModel):
    id: str
    contract_type: Optional[str] = None
    formula_type: str
    sla_ref: str
    title: str
    description: Optional[str] = None
    measurement_interval: str
    reporting_interval: str
    baseline_type: str
    compound_metric_rule: str
    ld_aggregation_method: str
    ld_computation_base: str
    status: str
    effective_from: date
    effective_until: Optional[date] = None
    dsl_version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SlaDetailResponse(SlaDefinitionResponse):
    metadata: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[SlaMetricResponse] = Field(default_factory=list)
    parameters: List[SlaParameterResponse] = Field(default_factory=list)
    condition_bands: List[SlaConditionBandResponse] = Field(default_factory=list)
    lookup_table: List[SlaLookupRowResponse] = Field(default_factory=list)
    guard_conditions: List[SlaGuardConditionResponse] = Field(default_factory=list)


class SlaOnboardResponse(SlaDetailResponse):
    """Returned only from POST /sla-masters — includes similar_slas warning list."""
    similar_slas: List[SlaDefinitionResponse] = Field(
        default_factory=list,
        description="Existing SLAs with the same contract_type + formula_type — review before using this SLA.",
    )


class SlaDslResponse(BaseModel):
    sla_id: str
    sla_ref: str
    dsl_version: int
    dsl_source: str
