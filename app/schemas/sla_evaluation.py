"""Pydantic schemas for SLA *severity* evaluation.

This module covers the severity-classification API only. LD (Liquidated
Damages) computation is intentionally not exposed here — it depends on
the project's quarterly payment, deliverable cost, contract base, etc.,
and lives in its own (future) API. Severity says "how bad is the breach";
LD says "what does that cost in rupees".

Evaluation is rooted at an SLA-Activity mapping. The mapping carries
instance-specific overrides (t_anchor_date, actual_start_date,
actual_end_date, ...) which take precedence over SLA-master defaults.
The SLA template declares which override keys are required via its
``placeholders`` array — the mapping form renders one input per entry.

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
    """Evaluate the severity of a single SLA-Activity mapping.

    period_start/period_end fall back to the mapping's overrides
    (actual_start_date / actual_end_date) when omitted.
    metric_observations can be omitted to trigger option (b) lookup from
    activity-stored observations (stubbed in this phase).

    NOTE: no ld_base_amount field. LD calculation has its own API; this
    one is purely about classifying the breach severity.
    """
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    metric_observations: List[MetricObservation] = Field(default_factory=list)


class ActivityEvaluationRequest(BaseModel):
    """Evaluate severity across every active SLA mapping on an activity.

    `observations_by_sla_ref` lets the caller pass fresh observations for some
    SLAs while leaving others to fall back on stored observations (stubbed).
    """
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    observations_by_sla_ref: Dict[str, List[MetricObservation]] = Field(
        default_factory=dict,
        description="sla_ref -> observations. Missing keys fall back to stored.",
    )


# ---------------------------------------------------------------------------
# Evaluation outputs
# ---------------------------------------------------------------------------

class BreachDetail(BaseModel):
    """How the metric fell into one of the SLA's severity bands.

    Strictly severity information — no LD contribution here. `rate_percent`
    is kept because it's a band attribute (the rate the contract assigns
    to that band), not a computed LD value; readers can use it later when
    the LD API multiplies it by base × duration.
    """
    metric_key: str
    band_label: Optional[str] = None
    observed_value: Optional[Decimal] = None
    days_in_band: Optional[int] = None
    severity_level: Optional[int] = None
    points_contribution: Optional[Decimal] = None
    rate_percent: Optional[Decimal] = None
    note: Optional[str] = None


class GuardResult(BaseModel):
    metric_key: str
    operator: str
    threshold_value: Decimal
    observed_value: Optional[Decimal] = None
    triggered: bool
    action: str
    action_description: Optional[str] = None


ScoringSource = Literal["project", "default", "unavailable"]


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

    # Project resolved from activity (via pmis-project-management). None when
    # project-management is unreachable or doesn't know this activity.
    project_id: Optional[str] = None

    # Which scoring chart was actually applied. ``project`` = read from the
    # project's severity_master. ``default`` = no project chart configured so
    # the RFP defaults were used. ``unavailable`` = project-management was
    # down or the activity is unknown — also fell back to defaults.
    severity_master_source: ScoringSource = "default"

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
        description="Aggregate counts: mappings_evaluated, mappings_skipped, "
                    "and per-severity-level breakdown. No LD aggregation here.",
    )
