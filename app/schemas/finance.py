"""Finance schemas — request / response models for /projects/{uuid}/finance.

Doc-finance contract surface. Two endpoints:

  - GET  /api/v3/projects/{uuid}/finance  → ``FinanceSummaryResponse``
  - PATCH /api/v3/projects/{uuid}/finance → body=``FinanceUpdateRequest``,
                                            response=``FinanceSummaryResponse``

Wire convention matches the rest of project-mgmt:
  * Request bodies accept BOTH camelCase aliases AND snake_case fields
    (``alias_generator=to_camel`` + ``populate_by_name=True``).
  * Response keys camelize at the HAL wrapper layer.
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


class CCNItem(ResponseModel):
    """One row of the CCN items table on the Finance page.

    Surfaces every live milestone (``category='ccn'``) and every live
    activity (``category='ccn'``) under the project. ``level`` is the
    display label the FE shows next to the row (``"Milestone"`` /
    ``"Activity"``); ``id`` is the entity UUID (FE may also surface the
    sequential ``displayCode`` separately via the M/A endpoints).
    """

    level: str
    id: str
    display_code: Optional[str] = None
    name: str
    ccn_value: Decimal
    created_at: Optional[datetime] = None


class FinanceSummaryResponse(ResponseModel):
    """Full finance summary returned by GET /projects/{uuid}/finance.

    All monetary fields are INR rupees as 2dp Decimals. ``isLocked``
    flips to True once the project is published (Q3.1 default —
    "Final onboarding"); after that the PATCH route rejects edits to
    any finance field with 409.

    ``ccnUsedPercent`` and ``ccnHeadroom`` are nullable so the wire
    can carry "—" semantics when the cap is dormant (TPV = 0); the
    HAL wrap layer keeps None values present as ``null`` (not dropped).
    """

    project_id: str
    project_code: Optional[str] = None
    status: str

    total_project_value_excl_tax: Decimal
    tax_percent: Decimal
    total_project_value_incl_tax: Decimal
    ccn_cap_percent: Decimal

    ccn_cap_amount: Decimal
    ccn_used: Decimal
    ccn_used_percent: Optional[Decimal] = None
    ccn_headroom: Optional[Decimal] = None
    effective_value: Decimal

    is_locked: bool
    cap_active: bool

    ccn_items: List[CCNItem] = Field(default_factory=list)


class FinanceUpdateRequest(BaseModel):
    """PATCH /projects/{uuid}/finance body — partial update.

    All three fields are optional; only sent fields are touched. The
    service layer rejects with 409 when the project is published
    (publish-lock, Q3.1 default). Schema bounds:
      * total_project_value_excl_tax ≥ 0
      * 0 ≤ tax_percent ≤ 100
      * 0 ≤ ccn_cap_percent ≤ 100
    """

    model_config = _REQUEST_CONFIG

    total_project_value_excl_tax: Annotated[
        Optional[Decimal], Field(default=None, ge=0)
    ] = None
    tax_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None
    ccn_cap_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None
