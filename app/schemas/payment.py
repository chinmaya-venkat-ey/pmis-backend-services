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

from datetime import date, datetime
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

    ``costTypeCode`` is REQUIRED. ``phase`` is required for ``fixed`` /
    ``resource_cost`` / ``transaction_cost`` rows and forced null for
    ``one_time``. Resource/transaction rows are standalone labelled expense
    lines (``lineLabel``); transaction total = ``perTransactionCost`` ×
    ``plannedTransactions``. All enforced in the service.
    """

    model_config = _REQUEST_CONFIG

    cost_type_code: Annotated[str, Field(min_length=1, max_length=32)]
    phase: Annotated[Optional[str], Field(default=None, max_length=64)] = None
    cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    # Tax as an exact AMOUNT (cost + taxAmount = total). taxPercent is legacy
    # (optional, unused).
    tax_amount: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    # Resource / transaction cost-line fields (they now bill via payment terms
    # like fixed; a transaction line's value = perTransactionCost × plannedTransactions).
    per_transaction_cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    planned_transactions: Annotated[Optional[int], Field(default=None, ge=0)] = None
    line_label: Annotated[Optional[str], Field(default=None, max_length=255)] = None
    # ``recurring_cost`` rows: the frequency the ``cost`` is spread across
    # (monthly/quarterly/half_yearly/yearly). Required for recurring, ignored
    # for every other type (enforced in the service).
    frequency_code: Annotated[Optional[str], Field(default=None, max_length=32)] = None
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
    per_transaction_cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    planned_transactions: Annotated[Optional[int], Field(default=None, ge=0)] = None
    line_label: Annotated[Optional[str], Field(default=None, max_length=255)] = None
    frequency_code: Annotated[Optional[str], Field(default=None, max_length=32)] = None
    milestone_ids: Optional[List[str]] = None
    position: Optional[int] = None


class CostItemSlaLdDetail(ResponseModel):
    """One activity's Track A LDs on this cost item (typed for the FE)."""
    activity_id: str
    sla_ref: Optional[str] = None
    ld_formula_rule: str
    ld_percent: Optional[Decimal] = None
    ld_amount: Optional[Decimal] = None
    ld_base_amount: Optional[Decimal] = None
    observed_value: Optional[Decimal] = None
    evaluated_on: Optional[str] = None
    status: Optional[str] = None


class CostItemSlaLdBlock(ResponseModel):
    """Track A LD summary attached to a cost item — Phase 1 deliverable
    LDs (SLA 001/002 per RFP §5.28.2.b/c). Present only when at least
    one linked activity has a Track A LD; absent otherwise."""
    total_amount: Decimal = Decimal("0.00")
    details: List[CostItemSlaLdDetail] = Field(default_factory=list)


class CostItemResponse(ResponseModel):
    id: str
    project_id: str
    cost_type_code: Optional[str] = None
    phase: Optional[str] = None
    cost: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_percent: Optional[Decimal] = None      # legacy (unused)
    per_transaction_cost: Optional[Decimal] = None
    planned_transactions: Optional[int] = None
    line_label: Optional[str] = None
    frequency_code: Optional[str] = None       # recurring_cost only: distribution frequency
    total: Decimal = Decimal("0.00")          # derived: line total (txn = perTxn × planned; else cost + tax)
    # recurring_cost only: the dated installment schedule the ``total`` is spread
    # across (from the milestone-timeline start over the project duration).
    # Computed on the payment page; empty for every other cost type.
    schedule: List["CfPoolInstallmentResponse"] = Field(default_factory=list)
    milestone_ids: List[str] = Field(default_factory=list)
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    # Phase E / P1b — Track A (per-deliverable) SLA LDs from contract-mgmt.
    # None when no Track A LDs apply; block populated when SLAs 001/002
    # (or MSIP milestone equivalents) have breached on any activity
    # linked to this cost item's milestones.
    sla_ld_deduction: Optional[CostItemSlaLdBlock] = None


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


class OneTimeUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/one-time.

    A phase opts into a share of the project one-time pool. ``enabled=false``
    clears it. ``enabled=true`` requires ``mode`` ('percent' of the one-time
    total | 'amount' in ₹) and ``value``. The chronologically LAST phase
    auto-absorbs the remainder and cannot be set explicitly.
    """

    model_config = _REQUEST_CONFIG

    enabled: bool
    mode: Annotated[Optional[str], Field(default=None, max_length=8)] = None
    value: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None

    @model_validator(mode="after")
    def _validate(self) -> "OneTimeUpdateRequest":
        if not self.enabled:
            self.mode = None
            self.value = None
            return self
        if self.mode not in ("percent", "amount"):
            raise ValueError("mode must be 'percent' or 'amount' when enabled.")
        if self.value is None:
            raise ValueError("value is required when enabled.")
        if self.mode == "percent" and self.value > Decimal("100"):
            raise ValueError("percent value cannot exceed 100.")
        return self


class CarryForwardAllocationResponse(ResponseModel):
    recipient_key: str
    recipient_kind: str                       # 'phase' | 'milestone'
    alloc_mode: str                           # 'percent' | 'amount' (how it was entered)
    input_value: Decimal = Decimal("0.00")    # the raw entered percent / amount
    percent: Decimal = Decimal("0.0000")      # normalised share (0..100)


class CfPoolInstallmentResponse(ResponseModel):
    """One dated installment of a FREQUENCY-based (pool) carry-forward. These are
    NOT added to any phase or milestone value — they are a schedule invoicing
    later draws from (the installments whose period has started and which no
    earlier invoice already took)."""
    period_index: int                         # calendar bucket index (monotonic)
    period_start: date
    period_end: date
    amount: Decimal = Decimal("0.00")
    status: str = "pending"                   # 'pending' | 'on_invoice'


# CostItemResponse.schedule forward-references CfPoolInstallmentResponse (defined
# above); resolve the reference now that the target class exists.
CostItemResponse.model_rebuild()


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
    # FREQUENCY (pool) methods only: the dated installment schedule this phase's
    # leftover becomes. Empty for applied (phase/milestone) methods. NOT part of
    # any phase total — surfaced for the (future) invoicing screen.
    pool: List["CfPoolInstallmentResponse"] = []
    # The per-period split value = leftover / remaining periods (each pool
    # installment carries this; the last absorbs the rounding remainder). 0 for
    # applied methods / when there is no pool.
    pool_per_period: Decimal = Decimal("0.00")


# ======================================================================= ccn cap

# Additional-cost kinds the finance panel can send. Only ``ccn`` is wired to
# backend logic (it sets the CCN cap); ``qgr``/``aqp`` are accepted so their
# UI works but carry no backend effect yet. Any other value is rejected.
ADDITIONAL_COST_TYPES = ("ccn", "qgr", "aqp")


class CcnCapUpdateRequest(BaseModel):
    """PATCH /projects/{uuid}/ccn-cap.

    The finance panel's additional-cost selector sends ``additionalCostType``
    plus its input. ``ccn`` sets the cap (``ccnCapPercent`` required); ``qgr``
    and ``aqp`` are accepted (via ``value``) but not yet acted on; unknown kinds
    are rejected."""

    model_config = _REQUEST_CONFIG

    additional_cost_type: Annotated[Optional[str], Field(default=None, max_length=16)] = None
    ccn_cap_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    value: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None

    @model_validator(mode="after")
    def _validate(self) -> "CcnCapUpdateRequest":
        if (self.additional_cost_type is not None
                and self.additional_cost_type not in ADDITIONAL_COST_TYPES):
            raise ValueError(
                "additionalCostType must be one of: " + ", ".join(ADDITIONAL_COST_TYPES))
        # CCN (the default when unspecified) requires a cap percent.
        if self.additional_cost_type in (None, "ccn") and self.ccn_cap_percent is None:
            raise ValueError("ccnCapPercent is required for the CCN cap.")
        return self


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
    resource_cost: Decimal = Decimal("0.00")
    transaction_cost: Decimal = Decimal("0.00")
    recurring_cost: Decimal = Decimal("0.00")
    # Project-level OPE (one-time / out-of-pocket) allocation guide — a
    # pre-validate/publish aid showing, cumulatively, how much of the
    # one_time_cost pool the user has ALLOCATED to phases vs. how much is still
    # PENDING (unallocated). Publishing requires pending == 0 (the pool must be
    # fully allocated). allocated + pending == one_time_cost; the percents are of
    # one_time_cost and sum to 100 (0/0 when there is no OPE).
    one_time_allocated: Decimal = Decimal("0.00")
    one_time_pending: Decimal = Decimal("0.00")
    one_time_allocated_percent: Decimal = Decimal("0.00")
    one_time_pending_percent: Decimal = Decimal("0.00")


class CcnBlock(ResponseModel):
    cap_percent: Decimal = Decimal("0.00")
    value: Decimal = Decimal("0.00")


class PhaseBlock(ResponseModel):
    phase: str
    sequence: Optional[int] = None                   # integer phase order
    phase_fixed_total: Decimal = Decimal("0.00")     # fixed-only subtotal (informational)
    # The full billable base a phase's milestone %s split: fixed + resource +
    # transaction cost lines in the phase (before one-time / carry-forward).
    phase_base_total: Decimal = Decimal("0.00")
    # The base used for milestone value + the 100% cap: phaseBaseTotal folded
    # with the one-time allocated to this phase + carry-forward received.
    # value = % × this.
    effective_phase_total: Decimal = Decimal("0.00")
    # This phase's share of the project one-time pool (₹). For the last phase this
    # is the auto-absorbed remainder. Already included in effectivePhaseTotal.
    one_time_allocated: Decimal = Decimal("0.00")
    one_time_enabled: bool = False            # phase opted in to an explicit share
    one_time_mode: Optional[str] = None       # 'percent' | 'amount' (null if not opted in)
    one_time_value: Optional[Decimal] = None  # the entered % or ₹ amount
    # Resource + transaction subtotal in this phase (informational — already part
    # of phaseBaseTotal / effectivePhaseTotal, billed via the milestone terms).
    expense_total: Decimal = Decimal("0.00")
    # The phase's full value = effectivePhaseTotal (fixed + resource +
    # transaction + one-time allocated + carry-forward received) PLUS the phase's
    # recurring total (see recurring_total).
    phase_total: Decimal = Decimal("0.00")
    # Recurring costs added to this phase: their combined total, and that total
    # distributed across the phase's date span at the project frequency — shown
    # as a dropdown schedule like the carry-forward pool. Recurring rows do NOT
    # bill via percentage payment terms; they pay out as this schedule.
    recurring_total: Decimal = Decimal("0.00")
    recurring_per_period: Decimal = Decimal("0.00")
    recurring_schedule: List[CfPoolInstallmentResponse] = Field(default_factory=list)
    # Phase date span — earliest milestone start / latest milestone end in the
    # phase (null if the phase has no live milestone). Inputs to the cycle count.
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    # Number of calendar-aligned billing cycles over [start_date, end_date] for the
    # phase's applied frequency (all terms in a phase share one). Null until a
    # valid frequency is applied / when dates are missing.
    cycle_count: Optional[int] = None
    # Whole project frequency periods (e.g. quarters) REMAINING after this phase
    # ends — from just after end_date to the project end. This is how many
    # installments a frequency (pool) carry-forward from this phase would spread
    # over. Null when dates/frequency are missing; 0 for the final phase.
    pending_cycles: Optional[int] = None
    payment_terms: List[PaymentTermResponse] = Field(default_factory=list)
    carry_forward: CarryForwardResponse


class PhaseSequenceUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/sequence — override the phase order."""

    model_config = _REQUEST_CONFIG

    sequence: Annotated[int, Field(ge=0)]


class SlaLdDeductionBlock(ResponseModel):
    """One quarter's SLA-LD deduction — Phase E, pulled from contract-mgmt.

    Rendered on the payment page as a negative line item alongside the
    normal cost blocks. AQP (Actual Quarterly Payment per RFP §5.28.1.d.h)
    is included so the FE doesn't have to redo the (PA - LD) + QGR math.

    ``status`` values (from contract-mgmt):
      * ``auto_closed``  quarterly cron auto-closed the row; ops can
                         still override until the invoice is raised.
      * ``overridden``   finance-role user replaced sum_ld_percent.
      * ``invoiced``     row is immutable — invoice raised.
      * ``blocked_missing_npqp``  leave-mgmt was unreachable at close time;
                                   payment page shows the block flagged so
                                   ops know to fix + re-close before invoice.
    """

    settlement_id: str
    fiscal_year: int
    quarter: int
    quarter_start: date
    quarter_end: date
    sum_ld_percent: Optional[Decimal] = None
    capped_ld_percent: Optional[Decimal] = None
    f_amount: Optional[Decimal] = None
    qgr_amount: Optional[Decimal] = None
    npqp: Optional[Decimal] = None
    ld_amount: Optional[Decimal] = None
    pa_amount: Optional[Decimal] = None
    aqp_amount: Optional[Decimal] = None
    status: str
    override_reason: Optional[str] = None


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
    # Phase E — one entry per quarter that has a settlement row in
    # contract-mgmt. Empty when contract-mgmt is unreachable OR when the
    # project has no active SLAs. Never breaks the page render.
    sla_ld_deductions: List[SlaLdDeductionBlock] = Field(default_factory=list)


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
