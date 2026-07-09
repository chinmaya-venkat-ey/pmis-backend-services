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
    model_config = {
        "json_schema_extra": {
            "example": {
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "metric_observations": [
                    {
                        "metric_key": "replacements_per_quarter",
                        "shape": "SINGLE_VALUE",
                        "single_value": "2",
                    }
                ],
            }
        }
    }
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    metric_observations: List[MetricObservation] = Field(default_factory=list)


class EvalFormInput(BaseModel):
    """One input field on the evaluation form, driven by the SLA's DSL.

    Recursive: ``fields`` carries child inputs for nested objects (WAC
    breakdown, BD+hours combos, etc.). For most SLAs there's just one
    top-level entry with ``type='number'``.
    """
    name: str = Field(..., description='Body key the FE writes the value under (usually "value").')
    type: str = Field(..., pattern=r"^(number|integer|text|list|object)$",
                      description='Widget type. "object" expects nested ``fields``.')
    label: str
    unit: Optional[str] = None
    placeholder: Optional[str] = None
    help: Optional[str] = None
    required: bool = True
    minimum: Optional[Decimal] = None
    maximum: Optional[Decimal] = None
    item_type: Optional[str] = Field(
        None, description='For ``type=list``: type of each item ("number", "integer").',
    )
    fields: Optional[List["EvalFormInput"]] = Field(
        None, description='For ``type=object``: sub-inputs.',
    )


class EvalFormPeriod(BaseModel):
    """Period defaults for the evaluate form — typically the activity's planned dates."""
    start_default: Optional[date] = None
    end_default: Optional[date] = None
    label_start: str = "Period Start"
    label_end: str = "Period End"


class EvalFormBand(BaseModel):
    """One row in the "RFP rule" reference card on the evaluate form."""
    severity: Optional[int] = None
    label: str
    range_min: Optional[Decimal] = None
    range_max: Optional[Decimal] = None
    unit: Optional[str] = None
    # For fixed-escalation SLAs that have no severity bands, just a
    # per-tier rate. Either ``severity`` or ``rate_percent`` is populated.
    rate_percent: Optional[Decimal] = None


class EvalFormSubmit(BaseModel):
    """Where the FE should POST when the user clicks Run."""
    method: str = "POST"
    url: str
    body_template: Dict[str, Any] = Field(default_factory=dict)


class EvalFormSchema(BaseModel):
    """Caller-friendly description of the evaluate form.

    The FE fetches this once per modal-open and renders inputs / bands /
    period defaults purely from the response — no per-formula JS, no
    hardcoded shape switching. When an SLA is updated (e.g. a new band
    added), the form automatically reflects it on the next open.
    """
    sla_ref: str
    sla_title: str
    activity_id: str
    mapping_id: str
    formula_type: str
    category: Optional[str] = None
    question: str
    explanation: str
    period: EvalFormPeriod
    inputs: List[EvalFormInput] = Field(default_factory=list)
    bands: List[EvalFormBand] = Field(default_factory=list)
    submit: EvalFormSubmit


# Resolve the forward reference (EvalFormInput nested in itself).
EvalFormInput.model_rebuild()


# ---------------------------------------------------------------------------
# Mapping form-schema — symmetric to EvalFormSchema, drives the *mapping*
# form (the screen where the operator attaches an SLA to an activity).
# Stage 2 of the user-facing flow:
#     onboard → MAPPING FORM ← here → map → evaluate-form → evaluate
# ---------------------------------------------------------------------------

class MappingFormSchema(BaseModel):
    """What the FE renders on the "Attach an SLA to this activity" modal.

    Driven by the SLA's stored ``placeholders`` JSONB. When the SLA's
    placeholders list is updated (e.g. a new "T_anchor_date" is added)
    the mapping form automatically reflects it on the next open — no
    FE deploy needed. Same design principle as the EvalFormSchema we
    introduced for stage 4.
    """
    sla_ref: str
    sla_title: str
    project_id: Optional[str] = None
    contract_type: Optional[str] = None
    category: Optional[str] = None
    formula_type: str
    # The friendly intro text + what the operator has to fill in.
    question: str = "Attach this SLA to an activity"
    explanation: str
    # ``effective_from`` always required; ``effective_until`` is
    # intentionally not asked anymore (mappings run open-ended until
    # retired). We surface both for parity.
    effective_from_default: Optional[date] = None
    # Placeholders from the SLA's DSL. The FE renders one input per row
    # — same EvalFormInput shape (recursive type) — and the values land
    # in ``overrides`` on the mapping create body.
    inputs: List[EvalFormInput] = Field(default_factory=list)
    # Submit target: POST /sla-activity-mappings with the body the FE
    # populates from inputs + effective_from.
    submit: "EvalFormSubmit"
    # Useful to surface so the operator can decide whether to use this
    # SLA at all on this activity.
    applied_on: Optional[str] = None
    applied_on_label: Optional[str] = None  # Human-readable expansion


class SimpleEvaluationRequest(BaseModel):
    """Caller-friendly single-SLA evaluation body.

    No metric_key, no observation `shape` field, no mapping_id. The backend
    looks up the active mapping by ``(activity_id, sla_ref)``, reads the
    SLA's primary metric, and translates ``value`` to the right internal
    observation shape:

      * number   → SINGLE_VALUE
      * list     → DAILY_VALUES
      * dict     → BAND_COUNTS (for severity-banded SLAs) or
                   WAC_BREAKDOWN (for wac SLAs)

    Most callers fill in only ``value``; period defaults to the activity's
    own date range when omitted.
    """
    model_config = {
        "json_schema_extra": {
            "example": {
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "value": 2,
            }
        }
    }
    period_start: Optional[date] = Field(
        None, description="Defaults to the activity's planned start date.",
    )
    period_end: Optional[date] = Field(
        None, description="Defaults to the activity's planned end date.",
    )
    value: Any = Field(
        ...,
        description="Observation value. Pass a number for one-shot SLAs "
                    "(e.g. 'replacements_per_quarter'), a list of numbers "
                    "for daily-reading SLAs, or a dict for band-counts / "
                    "wac SLAs.",
    )


class BulkEvaluationRequest(BaseModel):
    """Evaluate every SLA attached to an activity in one request.

    ``observations`` is a flat map keyed by SLA ref (e.g. ``PMU-SLA005``).
    Each value follows the same simple-shape rules as
    ``SimpleEvaluationRequest.value`` — number, list, or dict — and the
    backend translates each one into the right internal observation shape.

    SLAs that are mapped to the activity but absent from ``observations``
    are evaluated against stored observations (stubbed in this phase) and
    skipped if none exist.
    """
    model_config = {
        "json_schema_extra": {
            "example": {
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "observations": {
                    "PMU-SLA005": 2,
                    "PMU-SLA006": 22,
                    "PMU-SLA007": {"bd_per_month": 16, "hrs_per_month": 144},
                },
            }
        }
    }
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    observations: Dict[str, Any] = Field(
        default_factory=dict,
        description="Map of sla_ref → observation value. See "
                    "SimpleEvaluationRequest.value for the per-SLA shape.",
    )


class ActivityEvaluationRequest(BaseModel):
    """Evaluate severity across every active SLA mapping on an activity.

    `observations_by_sla_ref` lets the caller pass fresh observations for some
    SLAs while leaving others to fall back on stored observations (stubbed).
    """
    model_config = {
        "json_schema_extra": {
            "example": {
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "observations_by_sla_ref": {
                    "PMU-SLA005": [
                        {"metric_key": "replacements_per_quarter",
                         "shape": "SINGLE_VALUE", "single_value": "2"}
                    ],
                    "PMU-SLA006": [
                        {"metric_key": "kt_overlap_days",
                         "shape": "SINGLE_VALUE", "single_value": "15"}
                    ],
                },
            }
        }
    }
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
    # LD% this SLA's accumulated_points maps to on the project's LD chart
    # (project_ld_bands: highest tier whose points_threshold <= points). Falls
    # back to the RFP default chart when the project has none configured. None
    # when accumulated_points is None. NOT capped here — the 10% cap applies to
    # the whole-activity total only.
    ld_percent: Optional[Decimal] = None

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
    # Whole-activity LD roll-up: the total accumulated points across every
    # evaluated SLA mapping, and the LD% that total maps to on the project's LD
    # chart — CAPPED at 10% (the maximum LD allowed for the activity total).
    # None when there are no evaluated mappings / no chart is resolvable.
    total_points: Optional[Decimal] = None
    total_ld_percent: Optional[Decimal] = None
    summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregate counts: mappings_evaluated, mappings_skipped, "
                    "and per-severity-level breakdown.",
    )
