"""GET NPQP for one project × one quarter.

Consumed by:
  * QuarterlySettlementService (Phase D) — via direct service call, not HTTP.
  * FE settlement page — via HTTP, shown in the LD ₹ breakdown card.
  * Ops audits — "why did NPQP land at ₹X? show me F rows."

Auth: standard bearer (any authenticated user). No RBAC beyond the
existing service-level auth middleware.
"""
from __future__ import annotations

from datetime import date as _dt_date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.response import api_response
from app.db import get_db
from app.services.npqp_service import NpqpService
from app.utilities.quarter import parse_quarter_key, quarter_of


router = APIRouter(tags=["npqp"])


@router.get(
    "/npqp/projects/{project_id}",
    summary="NPQP (F + QGR) for one project × one quarter",
    description=(
        "Sums F from leave-mgmt's per-month cost endpoint (3 calls, one per "
        "month of the quarter) and adds the effective QGR from "
        "project.project_qgr_config. When leave-mgmt is unreachable the "
        "response status is 'leave_mgmt_unavailable' rather than 5xx so "
        "the settlement flow can log + block cleanly."
    ),
)
def get_npqp(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    quarter: Optional[str] = None,   # ?quarter=2026-Q3 or ?quarter=2026-05-10
):
    if not quarter:
        qk = quarter_of(_dt_date.today())
    else:
        try:
            if "-Q" in quarter.upper():
                qk = parse_quarter_key(quarter)
            else:
                qk = quarter_of(_dt_date.fromisoformat(quarter))
        except (ValueError, IndexError) as exc:
            raise ValidationError(
                f"Invalid quarter '{quarter}' — use '2026-Q2' or an ISO date.",
                code="invalid_quarter",
            ) from exc

    resp = NpqpService(db).compute(project_id, qk)
    return api_response(data=resp.model_dump(by_alias=True))
