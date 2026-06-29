"""Payment-module schemas — Project-Finance screen.

Surfaces (all project-scoped under /api/v3):

  Project Cost
    POST   /projects/{uuid}/cost-items          CostItemCreateRequest
    GET    /projects/{uuid}/cost-items
    GET    /cost-items/{id}
    PATCH  /cost-items/{id}                      CostItemUpdateRequest
    DELETE /cost-items/{id}    POST /cost-items/{id}/restore
        → CostItemResponse

  Payment Term
    POST   /projects/{uuid}/payment-terms        PaymentTermCreateRequest
    GET    /projects/{uuid}/payment-terms
    GET    /payment-terms/{id}
    PATCH  /payment-terms/{id}                    PaymentTermUpdateRequest
    DELETE /payment-terms/{id} POST /payment-terms/{id}/restore
        → PaymentTermResponse

  Term split PATCH /payment-terms/{id}/activities    PaymentTermActivitiesUpdateRequest
  CarryFwd  PUT /projects/{uuid}/phases/{phase}/carry-forward  CarryForwardUpdateRequest
  Phase seq PUT /projects/{uuid}/phases/{phase}/sequence       PhaseSequenceUpdateRequest
  CCN cap   PATCH /projects/{uuid}/ccn-cap            CcnCapUpdateRequest
  Page      GET /projects/{uuid}/payment-page         → PaymentPageResponse

Wire convention matches project-mgmt: request bodies accept BOTH camelCase
aliases AND snake_case; response keys camelize at the HAL wrapper layer.
All derived figures (total / value / qrg / ccn / summary totals) are
computed server-side. Every value field is optional for now.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel


_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


# ===================================================================== cost items

class CostItemCreateRequest(BaseModel):
    """POST /projects/{uuid}/cost-items.

    ``costTypeCode`` is REQUIRED (fixed / one_time). ``phase`` must be >= 0
    and is required for ``fixed`` rows (enforced in the service); it is
    forced null for ``one_time``.
    """

    model_config = _REQUEST_CONFIG

    cost_type_code: Annotated[str, Field(min_length=1, max_length=32)]
    phase: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    # Tax as an exact AMOUNT (cost + taxAmount = total). taxPercent is legacy
    # (optional, unused).
    tax_amount: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    milestone_ids: List[str] = Field(default_factory=list)
    position: Optional[int] = None


class CostItemUpdateRequest(BaseModel):
    """PATCH /cost-items/{id} — partial. ``costTypeCode`` cannot be unset to
    null; ``phase`` must be >= 0."""

    model_config = _REQUEST_CONFIG

    cost_type_code: Annotated[Optional[str], Field(default=None, min_length=1, max_length=32)]
    phase: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_amount: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    milestone_ids: Optional[List[str]] = None
    position: Optional[int] = None


class CostItemResponse(ResponseModel):
    id: str
    project_id: str
    cost_type_code: Optional[str] = None
    phase: Optional[str] = None
    cost: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_percent: Optional[Decimal] = None      # legacy (unused)
    total: Decimal = Decimal("0.00")          # derived: cost + taxAmount
    milestone_ids: List[str] = Field(default_factory=list)
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None


# ================================================================== payment terms

class PaymentTermUpdateRequest(BaseModel):
    """PATCH /payment-terms/{id} — partial.

    Payment-term ROWS are auto-managed from the Project-Cost milestone
    bundles (one row per milestone per phase). The user only fills in the
    schedule on each row: ``frequencyCode`` + ``percentOfPayment``. ``phase``
    and ``milestoneId`` are derived from the cost rows and are NOT editable
    here.
    """

    model_config = _REQUEST_CONFIG

    frequency_code: Annotated[Optional[str], Field(default=None, max_length=32)]
    percent_of_payment: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None


# ----------------------------------------------- per-activity payment split

class PaymentTermActivityAllocation(BaseModel):
    """One activity's share of a (partial-payment) milestone's payment term."""

    model_config = _REQUEST_CONFIG

    activity_id: Annotated[str, Field(min_length=1, max_length=36)]
    percent_of_payment: Annotated[Decimal, Field(ge=0, le=100)]


class PaymentTermActivitiesUpdateRequest(BaseModel):
    """PATCH /payment-terms/{id}/activities — set the per-activity split.

    Only valid for a partial-payment milestone's term. The allocations' percents
    must sum to the term's ``percentOfPayment`` (enforced in the service). Pass
    an empty list to clear the split.
    """

    model_config = _REQUEST_CONFIG

    activities: List[PaymentTermActivityAllocation] = Field(default_factory=list)


class PaymentTermActivityResponse(ResponseModel):
    activity_id: str
    activity_name: Optional[str] = None
    activity_display_code: Optional[str] = None   # A<milestonePos>.<activityPos>
    percent_of_payment: Optional[Decimal] = None  # defaults to an even split
    value: Decimal = Decimal("0.00")          # derived: percent × phase EFFECTIVE total


class PaymentTermResponse(ResponseModel):
    id: str
    project_id: str
    phase: Optional[str] = None               # display grouping only
    cost_item_id: Optional[str] = None        # the cost row this term belongs to (calc unit)
    milestone_id: Optional[str] = None
    payment_type: Optional[str] = None        # the milestone's payment type (partial/complete)
    frequency_code: Optional[str] = None
    percent_of_payment: Optional[Decimal] = None
    row_total: Decimal = Decimal("0.00")      # the cost row's own total (informational)
    value: Decimal = Decimal("0.00")          # derived: percent × phase EFFECTIVE total + carryReceived
    # Carry-forward received DIRECTLY by this milestone (milestone-wise mode).
    carry_received: Decimal = Decimal("0.00")
    # Per-activity split — populated only for partial-payment milestones.
    activities: List[PaymentTermActivityResponse] = Field(default_factory=list)
    # This milestone's own date span (drives the per-milestone cycle count).
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    # calendar-aligned billing cycles over THIS milestone's own start/end at the
    # phase's frequency. Null until a valid frequency is applied / dates missing.
    cycle_count: Optional[int] = None
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None


# ================================================================ carry forward

class CarryForwardAllocationItem(BaseModel):
    """One custom-split share in a carry-forward request: how much of the
    carrying phase's leftover goes to ``recipientKey`` (a subsequent phase name
    or milestone id). ``value`` is read per the request's ``allocationMode``
    (percent 0..100, or rupee amount)."""

    model_config = _REQUEST_CONFIG

    recipient_key: Annotated[str, Field(min_length=1, max_length=64)]
    value: Decimal = Decimal("0")


class CarryForwardUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/carry-forward.

    A carrying phase ALWAYS carries its entire leftover. ``enabled=false``
    clears it. ``enabled=true`` requires ``methodCode`` = a master carry-forward
    method (``masters.carry_forward_methods.code``):
      * ``"*_evenly"``  — split equally across subsequent phases / milestones.
      * ``"*_custom"``  — explicit per-recipient split; provide ``allocationMode``
                          ('percent' | 'amount') and ``allocations`` that fully
                          allocate the leftover (some recipients may be 0).
      * ``"time_*"``    — split across subsequent phases weighted by each phase's
                          payment-cycle count at the project frequency.

    Back-compat: the legacy ``mode`` field ('phase' | 'milestone') is still
    accepted and maps onto the matching ``*_evenly`` method when ``methodCode``
    is omitted.
    """

    model_config = _REQUEST_CONFIG

    enabled: bool
    method_code: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    # Deprecated alias — superseded by method_code.
    mode: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    # Custom-split inputs (only read when methodCode is a ``*_custom`` method).
    allocation_mode: Annotated[Optional[str], Field(default=None, max_length=8)] = None
    allocations: Optional[List[CarryForwardAllocationItem]] = None

    _MODE_TO_METHOD = {"phase": "phase_evenly", "milestone": "milestone_evenly"}

    @model_validator(mode="after")
    def _validate(self) -> "CarryForwardUpdateRequest":
        if not self.enabled:
            self.method_code = None
            self.mode = None
            self.allocation_mode = None
            self.allocations = None
            return self
        # Fold the legacy mode alias into method_code when method_code is absent.
        if not self.method_code and self.mode is not None:
            mapped = self._MODE_TO_METHOD.get(self.mode)
            if mapped is None:
                raise ValueError("mode must be 'phase' or 'milestone' when enabled.")
            self.method_code = mapped
        if not self.method_code:
            raise ValueError("methodCode is required when enabled.")
        # Custom methods require the allocation inputs (deep-validated in service).
        if self.method_code.endswith("_custom") and not self.allocations:
            raise ValueError("allocations are required for a custom carry-forward method.")
        return self


class CarryForwardAllocationResponse(ResponseModel):
    recipient_key: str
    recipient_kind: str                       # 'phase' | 'milestone'
    alloc_mode: str                           # 'percent' | 'amount' (how it was entered)
    input_value: Decimal = Decimal("0.00")    # the raw entered percent / amount
    percent: Decimal = Decimal("0.0000")      # normalised share (0..100)


class CarryForwardResponse(ResponseModel):
    enabled: bool = False
    method_code: Optional[str] = None         # master method code (null if disabled)
    leftover: Decimal = Decimal("0.00")       # this phase's leftover — the full carry basis
    carried_out: Decimal = Decimal("0.00")    # leftover carried out (0 if no recipients)
    # phase-wise inflow (grows the % base, equal per phase).
    received: Decimal = Decimal("0.00")
    # milestone-wise inflow — Σ of the per-milestone add-ons paid to THIS phase's
    # milestones. Proportional to the phase's milestone count; does NOT change
    # the % base or the milestone weightages.
    received_milestone: Decimal = Decimal("0.00")
    is_last_phase: bool = False               # no subsequent recipients → cannot carry
    # Saved custom-split shares for this phase (empty unless a *_custom method).
    allocations: List["CarryForwardAllocationResponse"] = []


# ======================================================================= ccn cap

class CcnCapUpdateRequest(BaseModel):
    """PATCH /projects/{uuid}/ccn-cap."""

    model_config = _REQUEST_CONFIG

    ccn_cap_percent: Annotated[Decimal, Field(ge=0, le=100)]


# ================================================================ phase frequency

class PhaseFrequencyUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/frequency — back-compat alias that now
    sets the PROJECT-level frequency (frequency is one value per project)."""

    model_config = _REQUEST_CONFIG

    frequency_code: Annotated[str, Field(min_length=1, max_length=32)]


class ProjectFrequencyUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/frequency — set the ONE billing frequency for the
    whole project (drives all cycle counts + time-based carry-forward)."""

    model_config = _REQUEST_CONFIG

    frequency_code: Annotated[str, Field(min_length=1, max_length=32)]


# ================================================================ aggregated page

class PaymentTotals(ResponseModel):
    total_contract_cost: Decimal = Decimal("0.00")
    fixed_cost: Decimal = Decimal("0.00")
    one_time_cost: Decimal = Decimal("0.00")


class CcnBlock(ResponseModel):
    cap_percent: Decimal = Decimal("0.00")
    value: Decimal = Decimal("0.00")


class PhaseBlock(ResponseModel):
    phase: str
    sequence: Optional[int] = None                   # integer phase order
    phase_fixed_total: Decimal = Decimal("0.00")     # original cost-rows total of the phase
    # The base used for milestone value + the 100% cap: phaseFixedTotal folded
    # with the one-time (first phase) + carry-forward received. value = % × this.
    effective_phase_total: Decimal = Decimal("0.00")
    # Phase date span — earliest milestone start / latest milestone end in the
    # phase (null if the phase has no live milestone). Inputs to the cycle count.
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    # Number of calendar-aligned billing cycles over [start_date, end_date] for the
    # phase's applied frequency (all terms in a phase share one). Null until a
    # valid frequency is applied / when dates are missing.
    cycle_count: Optional[int] = None
    payment_terms: List[PaymentTermResponse] = Field(default_factory=list)
    carry_forward: CarryForwardResponse


class PhaseSequenceUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/sequence — override the phase order."""

    model_config = _REQUEST_CONFIG

    sequence: Annotated[int, Field(ge=0)]


class PaymentPageResponse(ResponseModel):
    """Full payment page — read-only, reactive. Everything derived is
    recomputed on every GET so the API stays the source of truth."""

    project_id: str
    project_code: Optional[str] = None
    status: str
    is_locked: bool
    # The ONE project-level billing frequency (null until set). Drives every
    # cycle count below and time-based carry-forward.
    frequency_code: Optional[str] = None
    # Project's own date span + cycle count over it at the project frequency.
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    cycle_count: Optional[int] = None

    cost_items: List[CostItemResponse] = Field(default_factory=list)
    totals: PaymentTotals
    phases: List[PhaseBlock] = Field(default_factory=list)
    ccn: CcnBlock


# ==================================================================== cycle count

class CycleFrequency(str, Enum):
    """Frequencies the cycle-count endpoint supports — a subset of the frequency
    master (weekly / daily / one_time excluded for now)."""

    monthly = "monthly"
    quarterly = "quarterly"
    half_yearly = "half_yearly"
    yearly = "yearly"


class CycleCountResponse(ResponseModel):
    """Number of calendar-aligned billing cycles. ``cycles`` is null only for the
    project-level read when the project has no start/end dates set."""

    cycles: Optional[int] = None
