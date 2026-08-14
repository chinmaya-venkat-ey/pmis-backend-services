"""Pydantic schemas for SLA master onboarding."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Sub-table inputs
# ---------------------------------------------------------------------------

class SlaMetricInput(BaseModel):
    # #349: a real example so Swagger / generated forms don't render the
    # "string" / "1.1" placeholders that then get submitted and persisted.
    model_config = ConfigDict(json_schema_extra={"example": {
        "metric_key": "days_delayed",
        "display_name": "Days delayed",
        "unit": "days",
        "target_numeric": 5,
        "direction": "LOWER_BETTER",
        "is_primary": True,
    }})

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
    # #349: real example (no "string" / "1.1" placeholders).
    model_config = ConfigDict(json_schema_extra={"example": {
        "metric_key": "days_delayed",
        "band_label": "0.5% per day",
        "range_min": 1,
        "range_max": 15,
        "range_unit": "days",
        "rate_percent": 0.5,
        "sort_order": 0,
    }})

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
    action_description: Optional[str] = Field(None, max_length=500)
    guard_group_id: Optional[int] = Field(None, ge=0)


class SlaPlaceholderInput(BaseModel):
    """One mapping-time variable an SLA template requires.

    Declared on the template; rendered on the mapping form so the operator
    knows exactly what to fill in. Example::

        {"key": "T_anchor", "label": "T₀ — start of the deployment window",
         "type": "date", "required": true,
         "default_from": "activity.start_date",
         "help": "RFP §5.28.4.a — Governance tool deployment within T₀+6 months."}
    """
    key: str = Field(..., min_length=1, max_length=100,
                     pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
                     description="Machine name. Stored on mapping.overrides under this key.")
    label: str = Field(..., min_length=1, max_length=200,
                       description="What the operator sees on the mapping form.")
    type: str = Field(..., pattern=r"^(money|date|number|text)$",
                      description="Drives the input widget on the mapping form.")
    required: bool = Field(default=True,
                           description="When true the mapping form blocks submit until this is filled.")
    default_from: Optional[str] = Field(
        None, max_length=100,
        description='Activity field to autofill from, e.g. "activity.start_date", '
                    '"activity.actual_start_date", "activity.end_date". Leave null '
                    'for no autofill.',
    )
    help: Optional[str] = Field(
        None, max_length=500,
        description="Inline help shown under the input, usually an RFP reference.",
    )
    action_description: Optional[str] = None
    guard_group_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Main onboard request
# ---------------------------------------------------------------------------

class SlaOnboardRequest(BaseModel):
    # JSON-shape onboarding payload. Power-user / programmatic path —
    # caller already knows the metric/band structure exactly and wants
    # full control. The example below mirrors the seed for PMU-SLA005.
    model_config = {
        "json_schema_extra": {
            "example": {
                "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
                "contract_type": "PMU",
                "formula_type": "point_accumulation",
                "sla_ref": "PMU-SLA005",
                "title": "Resource Replacements per quarter",
                "description": "Number of contracted resources replaced during the quarter.",
                "category": "Resource Management",
                "measurement_interval": "QUARTERLY",
                "reporting_interval": "QUARTERLY",
                "ld_computation_base": "QUARTERLY_PAYMENT",
                "effective_from": "2024-04-01",
                "metrics": [{
                    "metric_key": "replacements_per_quarter",
                    "display_name": "Replacements / quarter",
                    "unit": "count", "target_numeric": "1",
                    "direction": "LOWER_BETTER", "is_primary": True,
                }],
                "condition_bands": [
                    {"metric_key": "replacements_per_quarter",
                     "band_label": "Sev 0 (within target)",
                     "range_max": "1", "range_unit": "count",
                     "severity_level": 0, "sort_order": 1},
                    {"metric_key": "replacements_per_quarter",
                     "band_label": "Sev 4 (exceeded target)",
                     "range_min": "1", "range_unit": "count",
                     "severity_level": 4, "sort_order": 2},
                ],
                "placeholders": [],
            }
        }
    }
    # Project the SLA belongs to. Per the PMC-contract model (one RFP =
    # one project = one SLA bundle), this is the primary scoping field.
    # SLAs are owned by a project from pmis-project-management — no longer
    # by a free-floating contract type. Required on every new SLA.
    project_id: Optional[str] = Field(
        None, max_length=36,
        description="UUID of the project (from pmis-project-management) that "
                    "owns this SLA. Optional — an SLA may be onboarded as a "
                    "project-agnostic template and scoped later (the model "
                    "column is nullable). Blocking onboarding on it also made "
                    "the flow hostage to the project-dropdown load (bug #256).",
    )
    # contract_type is now optional. When unset the service tries to derive
    # it from the project; when that fails the column stays NULL on the row.
    # Old rows (pre-project-scoping) keep their stamped value.
    contract_type: Optional[str] = Field(
        None, max_length=20, pattern=r"^(BSP|MSAP|MSIP|PMU)$",
        description="Optional. Derived from the project when omitted.",
    )
    formula_type: str = Field(
        ...,
        pattern=r"^(band_accumulation|point_accumulation|fixed_escalation|wac)$",
    )
    sla_ref: str = Field(..., max_length=50, pattern=r"^[A-Z0-9_-]+$")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    # Cadence + LD base default to "QUARTERLY / QUARTERLY / PQP" — what
    # PMU RFP §5.27.6 (as amended by the corrigendum, NPQP→PQP) spells out for
    # every SLA that doesn't say otherwise.
    # Required only if the RFP explicitly states a different value.
    measurement_interval: str = Field(
        "QUARTERLY", pattern=r"^(DAILY|WEEKLY|MONTHLY|QUARTERLY|ONE_TIME)$",
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
    # Settlement Track classifier. Optional: when omitted the service derives a
    # track-correct default from ld_computation_base (FIXED_AMOUNT ->
    # PER_UNIT_TIME_DELIVERABLE, else LADDER). Send the exact per-SLA rule to
    # override. A NULL rule would exclude the SLA from settlement entirely.
    ld_formula_rule: Optional[str] = None
    # effective_from is required on new SLAs (the only date the RFP
    # implicitly requires). effective_until stays optional — empty
    # means "open-ended", the most common case.
    effective_from: date = Field(
        default_factory=lambda: date(2024, 4, 1),
        description="When the template becomes valid. Default 2024-04-01 = FY24 start.",
    )
    effective_until: Optional[date] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Per-mapping variables operators must fill in when attaching this SLA
    # to an activity. See SlaPlaceholderInput. Default = empty (no
    # placeholders) — SLAs that plug straight onto an activity, e.g.
    # PMU-SLA005 "Resource replacements per quarter".
    placeholders: List[SlaPlaceholderInput] = Field(default_factory=list)
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
    # Partial-update body — send only the fields you want to change. The
    # example below sunsets an SLA (effective_until + status) and
    # tweaks the placeholder list at the same time.
    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Resource Replacements per quarter (FY26 revision)",
                "effective_until": "2026-12-31",
                "status": "ACTIVE",
                "placeholders": [
                    {"key": "approval_date_K", "label": "K — UIDAI approval date",
                     "type": "date", "required": True, "default_from": None,
                     "help": "RFP §5.28.3.f"},
                ],
            }
        }
    }
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
    project_id: Optional[str] = Field(None, max_length=36)
    placeholders: Optional[List[SlaPlaceholderInput]] = Field(
        None,
        description="Replaces the placeholder list when supplied (null = leave unchanged).",
    )


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
    project_id: Optional[str] = None
    placeholders: List[SlaPlaceholderInput] = Field(default_factory=list)
    # Image attachments are eagerly embedded so the list / detail responses
    # carry everything the FE needs to render the gallery in one
    # round-trip. Cached download URLs may expire — call the per-attachment
    # refresh-url endpoint to mint a new one. Forward reference avoids a
    # circular import with the attachment schemas.
    attachments: List["SlaAttachmentResponse"] = Field(default_factory=list)
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


class SlaRfpViewResponse(BaseModel):
    """RFP-friendly view of a stored SLA.

    What the operator sees on ``GET /sla-masters/{id}`` is the same
    shape they originally filled in on the onboarding form — no
    metric_key / sort_order / range_min / formula_type. Technical
    fields used by the severity engine live on the separate
    ``GET /sla-masters/{id}/parsed`` endpoint.

    Legacy field names (``description``, ``scope_text``,
    ``calculation_method``, ``ld_computation_base``) are preserved so the
    existing FE renderers continue to work; the RFP-friendly aliases
    (``definition``, ``scope``, ``calculation``, ``applied_on``) ride
    alongside them.
    """
    # Identification
    id: str
    sla_ref: str
    title: str
    project_id: Optional[str] = None
    contract_type: Optional[str] = None
    category: Optional[str] = None
    status: str

    # RFP text rows — legacy names kept for FE compat + RFP-friendly aliases
    description: Optional[str] = None    # original onboarding name
    definition: Optional[str] = None     # RFP "Definition of SLA"
    scope_text: Optional[str] = None
    scope: Optional[str] = None
    data_source: Optional[str] = None
    calculation_method: Optional[str] = None
    calculation: Optional[str] = None
    reports_submitted_to: Optional[str] = None

    # Cadence (both names)
    measurement_interval: str
    reporting_interval: str
    ld_computation_base: str
    applied_on: str

    # Lifetime
    effective_from: date
    effective_until: Optional[date] = None

    # What is measured — derived from primary / secondary metric
    measurement: Optional[SlaSimpleMeasurement] = None
    secondary_measurement: Optional[SlaSimpleMeasurement] = None

    # Severity threshold table — derived from condition_bands
    target_rows: List[SlaSimpleTargetRow] = Field(default_factory=list)

    # Linear LD escalation — derived from lookup_table or stashed onboarding metadata
    linear_escalation: Optional[SlaSimpleLinearEscalation] = None

    # Mapping-time variables
    placeholders: List[SlaPlaceholderInput] = Field(default_factory=list)

    # Image attachments — eagerly embedded so the View modal can render
    # the gallery without a second round-trip. Cached URLs may expire;
    # call the per-attachment refresh-url endpoint to mint a new one.
    attachments: List["SlaAttachmentResponse"] = Field(default_factory=list)

    # Audit
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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

    Preferred usage: the FE picks from the catalog at
    ``/api/v3/sla-input-variables`` and sends the picked entry's ``key``
    as ``metric_key``. Backend uses that key directly. When omitted (free-
    text fallback), backend slugifies ``display_name`` into the
    metric_key — preserved for backwards compat.
    """
    # #349: real example (no "string" placeholders in "What is Measured").
    model_config = ConfigDict(json_schema_extra={"example": {
        "metric_key": "days_delayed",
        "display_name": "Days delayed",
        "unit": "days",
        "target_value": 5,
    }})

    metric_key: Optional[str] = Field(
        None, max_length=100,
        description='Catalog metric_key when picked from /sla-input-variables. '
                    'Preferred over slugifying display_name so the same variable '
                    'used across multiple SLAs maps to the same metric_key.',
    )
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

    For multi-metric SLAs (PMU-SLA007's BD + hours) each row carries its
    own ``input_variable`` — the metric_key it guards. When omitted the
    row falls back to the SLA's primary measurement, which is the
    correct default for single-metric SLAs (PMU-SLA005 et al).
    """
    # #349: real example (no "string" / "1.1" placeholders in the Target rows).
    model_config = ConfigDict(json_schema_extra={"example": {
        "severity": 1,
        "threshold_label": "1 occurrence",
        "from_value": 0,
        "to_value": 1,
        "input_variable": "days_delayed",
    }})

    severity: Optional[int] = Field(
        None, ge=0, le=10,
        description='Severity level the row corresponds to. The PMU / MSAP / '
                    'BSP / MSIP RFPs use 0-4, but the schema permits up to 10 '
                    'so future contracts with finer-grained severity grids '
                    '(e.g. L0..L7) can onboard without a schema bump. NULL for '
                    'band_accumulation SLAs, whose bands carry a penalty rate '
                    'instead of a severity — see ``rate_percent``.',
    )
    rate_percent: Optional[Decimal] = Field(
        None, ge=0,
        description='LD / penalty rate for this band (band_accumulation SLAs, e.g. '
                    '0.5 = 0.5% per day-in-band). NULL for severity-graded SLAs.',
    )
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
    input_variable: Optional[str] = Field(
        None, max_length=100,
        description='metric_key this row guards. Omit to use the SLA\'s primary '
                    'measurement (the common case). Set per-row for multi-metric '
                    'SLAs where different bands check different variables.',
    )


class SlaSimpleLinearEscalation(BaseModel):
    """For deliverable / query SLAs that escalate LD% per unit time.

    Backend expands this into a verbose lookup_table behind the scenes.
    Examples:
      * Deliverable Submission RFP §5.28.2.b: 0.5% per week, no grace.
      * Query Resolution      RFP §5.28.3.a: 0.1% per day, 3-day grace.

    Field aliasing: the canonical rate field is ``rate_per_unit_percent``,
    but every published example (Swagger, OpenAPI schema) historically
    showed the shorter ``rate_percent`` — so clients built from the docs
    sent that name and got a 422 "Field required" on exactly the
    deliverable / query SLAs that need this block (SLA001-type). We accept
    both spellings (``rate_percent`` → ``rate_per_unit_percent``, ``grace``
    → ``grace_units``) so onboarding no longer depends on which name the
    caller copied. ``populate_by_name`` keeps the canonical names working.
    """
    model_config = {"populate_by_name": True}

    rate_per_unit_percent: Decimal = Field(
        ..., gt=0, le=10,
        validation_alias=AliasChoices("rate_per_unit_percent", "rate_percent"),
        description='LD% applied per unit of delay. 0.5 means 0.5% per week. '
                    'Alias: rate_percent.',
    )
    unit: str = Field(..., pattern=r"^(day|week|month)$",
                      description='Time unit. Determines unit label and tier count.')
    grace_units: int = Field(
        0, ge=0, le=365,
        validation_alias=AliasChoices("grace_units", "grace"),
        description='Number of units allowed before LD kicks in (e.g. 3 days). '
                    'Alias: grace.',
    )
    max_units: int = Field(
        20, ge=1, le=365,
        description='How many tiers to seed in the lookup table. Default 20 covers the typical cap.',
    )


class SlaFromRfpRequest(BaseModel):
    """Non-technical SLA onboarding payload — mirrors the RFP table 1:1.

    Fill order matches the rows the user reads in the contract PDF. Every
    technical concept (metric_key, sort_order, condition_band shape, lookup
    rows) is derived by the backend.

    Sent as the ``payload`` form field on POST /sla-masters/from-rfp.
    """
    model_config = {
        # FE onboarding wizard sometimes sends the DB-column names
        # (description / calculation_method / scope_text) instead of the
        # RFP-form names (definition / calculation / scope). Accept both
        # via AliasChoices below so payloads don't silently drop fields.
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "sla_ref": "PMU-SLA001",
                "title": "Non-submission of deliverable",
                "project_id": "31eefb48-c2d3-4a4a-8fc7-a23b84d08e45",
                "contract_type": "PMU",
                "category_code": "DELIVERABLE_SUBMISSION",
                "definition": "Failure to submit the deliverable on or before the agreed date.",
                "scope": "Applies to all Phase-1 deliverables D1 through D8.",
                "data_source": "Project Tracker — deliverable submission timestamps.",
                "calculation": "LD = 0.5% of deliverable cost per week of delay; part-weeks count as full weeks.",
                "reports_submitted_to": "Concerned UIDAI Stakeholders",
                "measurement_interval": "ONE_TIME",
                "reporting_interval": "QUARTERLY",
                "applied_on": "FIXED_AMOUNT",
                "effective_from": "2024-04-01",
                "measurement": {"display_name": "Weeks delayed", "unit": "weeks"},
                "target_rows": [],
                "linear_escalation": {
                    "rate_per_unit_percent": "0.5", "unit": "week", "grace_units": 0, "max_units": 20,
                },
                "placeholders": [
                    {"key": "ld_base_amount",
                     "label": "Cost of this deliverable (₹)",
                     "type": "money", "required": True,
                     "default_from": None,
                     "help": "Used as the LD% base for this deliverable. RFP §5.28.2.b."},
                ],
            }
        }
    }
    # ── 1. Identification ──
    sla_ref: str = Field(..., max_length=50, pattern=r"^[A-Z0-9_-]+$",
                         description='RFP "SLA number", e.g. "PMU-SLA004".')
    title: str = Field(..., min_length=1, max_length=500,
                       description='Title shown above the RFP table.')
    project_id: Optional[str] = Field(
        None, max_length=36,
        description='UUID of the project (from pmis-project-management) that '
                    'owns this SLA. Optional — may be onboarded as a '
                    'project-agnostic template and scoped later.',
    )
    # contract_type is now optional. Derived from the project when omitted.
    contract_type: Optional[str] = Field(
        None, max_length=20, pattern=r"^(BSP|MSAP|MSIP|PMU)$",
        description="Optional. Derived from the project when omitted.",
    )
    category_code: str = Field(..., max_length=50,
                               description='Code from sla_category_master (decides the engine).')

    # ── 2. RFP text rows ──
    # AliasChoices lets the FE send either the RFP-form name or the
    # DB-column name — both land here. Prior to this the FE was silently
    # dropping description / calculation_method / scope_text because they
    # didn't match the RFP-form names.
    definition: Optional[str] = Field(
        None, description='RFP row "Definition of SLA".',
        validation_alias=AliasChoices("definition", "description"),
    )
    scope: Optional[str] = Field(
        None, description='RFP row "Scope of SLA".',
        validation_alias=AliasChoices("scope", "scope_text"),
    )
    data_source: Optional[str] = Field(
        None, max_length=255,
        description='RFP row "Process to capture raw data for SLA calculations".',
    )
    calculation: Optional[str] = Field(
        None, description='RFP row "SLA calculation" — plain-English formula.',
        validation_alias=AliasChoices("calculation", "calculation_method"),
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
        description='LD base. QUARTERLY_PAYMENT = PQP; FIXED_AMOUNT = deliverable cost.',
    )
    # Settlement Track classifier — optional; the service derives a track-correct
    # default from applied_on when omitted (else the SLA gets no LD). Send the
    # exact per-SLA rule (PER_UNIT_TIME_DELIVERABLE / LADDER / PER_OCCURRENCE / …)
    # to override.
    ld_formula_rule: Optional[str] = None
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

    # ── 6. Per-mapping variables operators must fill in ──
    # Empty = the SLA plugs straight onto an activity without any extra
    # input. Most PMU SLAs land here. SLA 010 needs T_anchor, SLA 008
    # needs an approval date, SLA 001/002 need a deliverable cost — those
    # rows declare it once on the template; the mapping form renders the
    # right input automatically.
    placeholders: List[SlaPlaceholderInput] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Forward-reference resolution
# ---------------------------------------------------------------------------
# SlaAttachmentResponse lives in a sibling module to avoid a top-level
# circular import. Pull it in here and rebuild the response models that
# reference it via string so Pydantic can finalise their schemas.

from app.schemas.sla_attachment import SlaAttachmentResponse  # noqa: E402

SlaDefinitionResponse.model_rebuild()
SlaRfpViewResponse.model_rebuild()
SlaDetailResponse.model_rebuild()
SlaOnboardResponse.model_rebuild()
