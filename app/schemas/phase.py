"""Response schema for the lightweight project-phases endpoint
(``GET /api/v3/projects/{uuid}/phases``) — each phase's date span plus its
delivery-model flags. No finance totals (see the payment page for those)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.schemas._base import ResponseModel


class ProjectPhaseSummary(ResponseModel):
    # The phase identifier as used across finance/cost items ("1", "2", "D11", …).
    phase: str
    # Date span = earliest milestone start / latest milestone end in the phase
    # (same derivation as the payment page). Null if the phase has no live milestone.
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    # Delivery-model flags — true if any of the phase's milestones carries the flag.
    is_resource_based: bool = False
    is_transaction_based: bool = False


class ProjectPhasesResponse(ResponseModel):
    phases: List[ProjectPhaseSummary]
