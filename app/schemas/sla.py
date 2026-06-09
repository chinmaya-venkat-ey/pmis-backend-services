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
    # ── RFP-native presentation fields (UIDAI RFP §5.28 row headers) ──
    # All optional for backward compatibility. category replaces
    # formula_type for the user-facing form; formula_type still drives
    # evaluator dispatch.
    category: Optional[str] = Field(
        None, max_length=50,
        description='User-facing SLA category (e.g. "Deliverable Submission", '
                    '"Resource Management", "Governance Tool"). Replaces '
                    'formula_type on the form.',
    )
    scope_text: Optional[str] = Field(
        None, description='RFP row "Scope of SLA".',
    )
    data_source: Optional[str] = Field(
        None, max_length=255,
        description='RFP row "Process to capture raw data for SLA calculations".',
    )
    calculation_method: Optional[str] = Field(
        None, description='RFP row "SLA calculation" — plain-English formula.',
    )
    reports_submitted_to: Optional[str] = Field(
        None, max_length=255,
        description='RFP row "Reports and Data submitted to".',
    )
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
    # RFP-native fields — all optional partial-update.
    category: Optional[str] = Field(None, max_length=50)
    scope_text: Optional[str] = None
    data_source: Optional[str] = Field(None, max_length=255)
    calculation_method: Optional[str] = None
    reports_submitted_to: Optional[str] = Field(None, max_length=255)


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
    # RFP-native presentation fields.
    category: Optional[str] = None
    scope_text: Optional[str] = None
    data_source: Optional[str] = None
    calculation_method: Optional[str] = None
    reports_submitted_to: Optional[str] = None
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


# ---------------------------------------------------------------------------
# RFP-shape onboarding (POST /sla-masters/from-rfp)
#
# This payload mirrors the 9-row UIDAI PMU SLA tables in §5.28 1:1, so a
# non-technical user can fill it just by copying from the contract document.
# Backend translates this into the full SlaOnboardRequest and calls the same
# create_from_form code path, so seeds, evaluator and PATCH editing all keep
# working without change.
# ---------------------------------------------------------------------------

class SlaSimpleMeasurement(BaseModel):
    """The single thing the SLA observes (e.g. "days delayed").

    The user types a display name and unit; backend slugifies the display
    name into the technical ``metric_key`` so the form never asks for it.
    """
    display_name: str = Field(..., max_length=255,
                              description='User-facing name of the measurement, e.g. "Days delayed".')
    unit: str = Field("", max_length=50,
                      description='Unit shown next to the value, e.g. "days", "weeks", "%".')
    target_value: Optional[Decimal] = Field(
        None, description='Optional target / threshold value carried as a reference number.',
    )


class SlaSimpleTargetRow(BaseModel):
    """One row of the RFP "Target" sub-table (severity-banded SLAs).

    The user fills in the RFP's exact wording in ``threshold_label`` (e.g.
    "1 occurrence", ">= 16 business days") and the numeric bounds the
    evaluator should use to decide which row a measurement lands in.
    """
    severity: int = Field(..., ge=0, le=4,
                          description='Severity level the row corresponds to (RFP §5.28.1.a).')
    threshold_label: Optional[str] = Field(
        None, max_length=100,
        description='Human-readable threshold copied from the RFP, e.g. "1 occurrence".',
    )
    from_value: Optional[Decimal] = Field(
        None, description='Lower bound (exclusive). Leave null for "no lower bound".',
    )
    to_value: Optional[Decimal] = Field(
        None, description='Upper bound (inclusive). Leave null for "no upper bound".',
    )


class SlaSimpleLinearEscalation(BaseModel):
    """For deliverable / query SLAs that escalate LD% per unit time.

    Backend expands this into a verbose lookup_table behind the scenes.
    Examples:
      * Deliverable Submission RFP §5.28.2.b: 0.5% per week, no grace.
      * Query Resolution      RFP §5.28.3.a: 0.1% per day, 3-day grace.
    """
    rate_per_unit_percent: Decimal = Field(
        ..., gt=0, le=10,
        description='LD% applied per unit of delay. 0.5 means 0.5% per week.',
    )
    unit: str = Field(..., pattern=r"^(day|week|month)$",
                      description='Time unit. Determines unit label and tier count.')
    grace_units: int = Field(0, ge=0, le=365,
                             description='Number of units allowed before LD kicks in (e.g. 3 days).')
    max_units: int = Field(
        20, ge=1, le=365,
        description='How many tiers to seed in the lookup table. Default 20 covers the typical cap.',
    )


class SlaFromRfpRequest(BaseModel):
    """Non-technical SLA onboarding payload — mirrors the RFP table 1:1.

    Fill order matches the rows the user reads in the contract PDF. Every
    technical concept (metric_key, sort_order, condition_band shape, lookup
    rows) is derived by the backend.
    """
    # ── 1. Identification ──
    sla_ref: str = Field(..., max_length=50, pattern=r"^[A-Z0-9_-]+$",
                         description='RFP "SLA number", e.g. "PMU-SLA004".')
    title: str = Field(..., min_length=1, max_length=500,
                       description='Title shown above the RFP table.')
    contract_type: str = Field(..., max_length=20, pattern=r"^(BSP|MSAP|MSIP|PMU)$")
    category_code: str = Field(..., max_length=50,
                               description='Code from sla_category_master (decides the engine).')

    # ── 2. RFP text rows ──
    definition: Optional[str] = Field(
        None, description='RFP row "Definition of SLA".',
    )
    scope: Optional[str] = Field(
        None, description='RFP row "Scope of SLA".',
    )
    data_source: Optional[str] = Field(
        None, max_length=255,
        description='RFP row "Process to capture raw data for SLA calculations".',
    )
    calculation: Optional[str] = Field(
        None, description='RFP row "SLA calculation" — plain-English formula.',
    )
    reports_submitted_to: Optional[str] = Field(
        None, max_length=255,
        description='RFP row "Reports and Data submitted to".',
    )

    # ── 3. Cadence + Applied On ──
    measurement_interval: str = Field(
        "QUARTERLY",
        pattern=r"^(DAILY|WEEKLY|MONTHLY|QUARTERLY|ONE_TIME)$",
    )
    reporting_interval: str = Field(
        "QUARTERLY",
        pattern=r"^(WEEKLY|MONTHLY|QUARTERLY|ANNUAL)$",
    )
    applied_on: str = Field(
        "QUARTERLY_PAYMENT",
        pattern=r"^(QUARTERLY_PAYMENT|ANNUAL_PAYMENT|FIXED_AMOUNT)$",
        description='LD base. QUARTERLY_PAYMENT = NPQP; FIXED_AMOUNT = deliverable cost.',
    )
    effective_from: date = Field(default_factory=lambda: date(2024, 4, 1))
    effective_until: Optional[date] = None

    # ── 4. What is measured (one or two) ──
    measurement: SlaSimpleMeasurement
    secondary_measurement: Optional[SlaSimpleMeasurement] = Field(
        None,
        description='Used for compound SLAs (RFP §5.28.3.e). Captured for the form; '
                    'evaluator treats the primary measurement as authoritative until '
                    'per-band AND conditions are introduced.',
    )

    # ── 5a. Target — severity bands (for severity-driven categories) ──
    target_rows: List[SlaSimpleTargetRow] = Field(
        default_factory=list,
        description='Severity threshold rows from the RFP. Required for severity '
                    'categories (Recommendation Quality, Resource Management, '
                    'Governance Tool).',
    )

    # ── 5b. Linear escalation (for time-based categories) ──
    linear_escalation: Optional[SlaSimpleLinearEscalation] = Field(
        None,
        description='Alternative to target_rows for Deliverable Submission and Query '
                    'Resolution categories. Backend expands into a lookup table.',
    )
