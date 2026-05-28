"""Pydantic schemas for SLA evaluation.

Evaluation is rooted at an SLA-Activity mapping. The mapping carries instance-
specific overrides (t_anchor_date, actual_start_date, actual_end_date,
ld_base_amount, ...) which take precedence over SLA-master defaults.

Observation shapes are form-friendly: frontend collects values via widgets
(picklist + number field per metric) and posts a typed payload — no DSL.

Supported shapes per formula type:
  SINGLE_VALUE   - one observed value         (point_accumulation, fixed_escalation)
  DAILY_VALUES   - one value per day          (band_accumulation, daily metrics)
  BAND_COUNTS    - days_in_band per band      (band_accumulation, pre-aggregated)
  WAC_BREAKDOWN  - defect counts + apps base  (wac)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Observation inputs (option (a) — fresh from the form)
# ---------------------------------------------------------------------------

ObservationShape = Literal["SINGLE_VALUE", "DAILY_VALUES", "BAND_COUNTS", "WAC_BREAKDOWN"]


class MetricObservation(BaseModel):
    metric_key: str = Field(..., max_length=100)
    shape: ObservationShape

    single_value: Optional[Decimal] = None
    daily_values: Optional[List[Decimal]] = None
    band_counts: Optional[Dict[str, int]] = Field(
        None, description="band_label -> days_in_band"
    )
    wac_breakdown: Optional[Dict[str, Decimal]] = Field(
        None,
        description=(
            "Keys: blocker, critical, major, minor, applications, baseline, "
            "and optionally previous_wac for variance step calculation."
        ),
    )


class MappingEvaluationRequest(BaseModel):
    """Evaluate a single SLA-Activity mapping.

    period_start/period_end fall back to the mapping's overrides
    (actual_start_date / actual_end_date) when omitted.
    ld_base_amount falls back to overrides.ld_base_amount.
    metric_observations can be omitted to trigger option (b) lookup from
    activity-stored observations (stubbed in this phase).
    """
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    ld_base_amount: Optional[Decimal] = None
    metric_observations: List[MetricObservation] = Field(default_factory=list)


class ActivityEvaluationRequest(BaseModel):
    """Evaluate every active SLA mapping on an activity.

    `observations_by_sla_ref` lets the caller pass fresh observations for some
    SLAs while leaving others to fall back on stored observations (stubbed).
    """
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    ld_base_amount_overrides: Dict[str, Decimal] = Field(
        default_factory=dict,
        description="sla_ref -> ld_base_amount override for this run.",
    )
    observations_by_sla_ref: Dict[str, List[MetricObservation]] = Field(
        default_factory=dict,
        description="sla_ref -> observations. Missing keys fall back to stored.",
    )


# ---------------------------------------------------------------------------
# Evaluation outputs
# ---------------------------------------------------------------------------

class BreachDetail(BaseModel):
    metric_key: str
    band_label: Optional[str] = None
    observed_value: Optional[Decimal] = None
    days_in_band: Optional[int] = None
    severity_level: Optional[int] = None
    points_contribution: Optional[Decimal] = None
    rate_percent: Optional[Decimal] = None
    contribution_percent: Optional[Decimal] = Field(
        None, description="This band's contribution to the SLA's LD percent for the period."
    )
    note: Optional[str] = None


class GuardResult(BaseModel):
    metric_key: str
    operator: str
    threshold_value: Decimal
    observed_value: Optional[Decimal] = None
    triggered: bool
    action: str
    action_description: Optional[str] = None


class MappingEvaluationResponse(BaseModel):
    mapping_id: str
    activity_id: str
    sla_id: str
    sla_ref: str
    contract_type: Optional[str] = None
    formula_type: str

    period_start: date
    period_end: date

    severity_level: Optional[int] = None
    accumulated_points: Optional[Decimal] = None
    ld_percent: Optional[Decimal] = None
    ld_amount: Optional[Decimal] = None

    breaches: List[BreachDetail] = Field(default_factory=list)
    guards: List[GuardResult] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    overrides_applied: Dict[str, Any] = Field(
        default_factory=dict,
        description="Which override keys from the mapping were used during this evaluation.",
    )


class ActivityEvaluationResponse(BaseModel):
    activity_id: str
    period_start: date
    period_end: date
    mapping_results: List[MappingEvaluationResponse] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregate counts: mappings_evaluated, mappings_skipped, total_ld_percent, etc.",
    )
