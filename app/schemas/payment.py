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

  QRG       PUT /projects/{uuid}/phases/{phase}/qrg   QrgUpdateRequest → QrgResponse
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
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field
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
    phase: Annotated[Optional[int], Field(default=None, ge=0)] = None
    cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    milestone_ids: List[str] = Field(default_factory=list)
    position: Optional[int] = None


class CostItemUpdateRequest(BaseModel):
    """PATCH /cost-items/{id} — partial. ``costTypeCode`` cannot be unset to
    null; ``phase`` must be >= 0."""

    model_config = _REQUEST_CONFIG

    cost_type_code: Annotated[Optional[str], Field(default=None, min_length=1, max_length=32)]
    phase: Annotated[Optional[int], Field(default=None, ge=0)] = None
    cost: Annotated[Optional[Decimal], Field(default=None, ge=0)] = None
    tax_percent: Annotated[Optional[Decimal], Field(default=None, ge=0, le=100)] = None
    milestone_ids: Optional[List[str]] = None
    position: Optional[int] = None


class CostItemResponse(ResponseModel):
    id: str
    project_id: str
    cost_type_code: Optional[str] = None
    phase: Optional[int] = None
    cost: Optional[Decimal] = None
    tax_percent: Optional[Decimal] = None
    total: Decimal = Decimal("0.00")          # derived: cost × (1 + tax/100)
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


class PaymentTermResponse(ResponseModel):
    id: str
    project_id: str
    phase: Optional[int] = None               # display grouping only
    cost_item_id: Optional[str] = None        # the cost row this term belongs to (calc unit)
    milestone_id: Optional[str] = None
    frequency_code: Optional[str] = None
    percent_of_payment: Optional[Decimal] = None
    row_total: Decimal = Decimal("0.00")      # the cost row's total — the base for value/cap
    value: Decimal = Decimal("0.00")          # derived: percent × rowTotal
    position: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None


# =========================================================================== qrg

class QrgUpdateRequest(BaseModel):
    """PUT /projects/{uuid}/phases/{phase}/qrg."""

    model_config = _REQUEST_CONFIG

    qrg_applied: bool


class QrgResponse(ResponseModel):
    phase: int
    applied: bool
    percent: Optional[Decimal] = None         # derived: 100 − Σ percent_of_payment
    value: Optional[Decimal] = None           # derived: phase fixed total − Σ value


# ======================================================================= ccn cap

class CcnCapUpdateRequest(BaseModel):
    """PATCH /projects/{uuid}/ccn-cap."""

    model_config = _REQUEST_CONFIG

    ccn_cap_percent: Annotated[Decimal, Field(ge=0, le=100)]


# ================================================================ aggregated page

class PaymentTotals(ResponseModel):
    total_contract_cost: Decimal = Decimal("0.00")
    fixed_cost: Decimal = Decimal("0.00")
    one_time_cost: Decimal = Decimal("0.00")


class CcnBlock(ResponseModel):
    cap_percent: Decimal = Decimal("0.00")
    value: Decimal = Decimal("0.00")


class PhaseBlock(ResponseModel):
    phase: int
    phase_fixed_total: Decimal = Decimal("0.00")
    payment_terms: List[PaymentTermResponse] = Field(default_factory=list)
    qrg: QrgResponse


class PaymentPageResponse(ResponseModel):
    """Full payment page — read-only, reactive. Everything derived is
    recomputed on every GET so the API stays the source of truth."""

    project_id: str
    project_code: Optional[str] = None
    status: str
    is_locked: bool

    cost_items: List[CostItemResponse] = Field(default_factory=list)
    totals: PaymentTotals
    phases: List[PhaseBlock] = Field(default_factory=list)
    ccn: CcnBlock
