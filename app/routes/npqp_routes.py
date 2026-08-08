"""GET NPQP for one project × one quarter.

Consumed by:
  * QuarterlySettlementService (Phase D) — via direct service call, not HTTP.
  * FE settlement page — via HTTP, shown in the LD ₹ breakdown card.
  * Ops audits — "why did NPQP land at ₹X? show me F rows."

Auth: standard bearer (any authenticated user). No RBAC beyond the
existing service-level auth middleware.

Response envelope (standard api_response wrapper):
  {"data": <NpqpResponse>, "message": null, "error": null, "status": 200}
"""
from __future__ import annotations

from datetime import date as _dt_date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.response import api_response
from app.db import get_db
from app.services.npqp_service import NpqpService
from app.utilities.project_anchor import project_anchor
from app.utilities.quarter import parse_quarter_key, quarter_of


router = APIRouter(tags=["npqp"])


_NPQP_EXAMPLE_OK = {
    "projectId": "60c67666-895f-4138-bd99-c907b571e933",
    "fiscalYear": 2026,
    "quarter": 3,
    "quarterStart": "2026-07-01",
    "quarterEnd": "2026-09-30",
    "fAmount": "1310096.91",
    "qgrAmount": "0.00",
    "npqp": "1310096.91",
    "status": "ok",
    "perMonth": [
        {
            "resourceId": "421", "employeeName": "Sanju",
            "year": 2026, "month": 7,
            "monthlyRate": "100874.00", "cost": "94295.26",
        }
    ],
}

_NPQP_EXAMPLE_BLOCKED = {
    "projectId": "60c67666-...",
    "fiscalYear": 2026, "quarter": 3,
    "quarterStart": "2026-07-01", "quarterEnd": "2026-09-30",
    "fAmount": "0", "qgrAmount": "0", "npqp": "0",
    "status": "leave_mgmt_unavailable",
    "perMonth": [],
}


@router.get(
    "/npqp/projects/{project_id}",
    summary="NPQP (F + QGR) for one project × one quarter",
    description=(
        "Sums F from leave-mgmt's per-month cost endpoint (3 calls, one "
        "per month of the quarter) and adds the effective QGR from "
        "project.project_qgr_config.\n\n"
        "When leave-mgmt is unreachable, the response is 200 with "
        "status='leave_mgmt_unavailable' (never 5xx) so the settlement "
        "flow can log + block cleanly.\n\n"
        "quarter format: Y1-Q1 .. Yn-Q4 (contract-relative, anchored on project start), or any ISO date in the "
        "target quarter. Defaults to the current quarter."
    ),
    responses={
        200: {"description": "NPQP breakdown envelope",
              "content": {"application/json": {
                  "examples": {
                      "ok": {"summary": "Normal path — leave-mgmt returned data",
                             "value": {"data": _NPQP_EXAMPLE_OK,
                                       "message": None, "error": None, "status": 200}},
                      "blocked": {"summary": "leave-mgmt unavailable — status flagged",
                                   "value": {"data": _NPQP_EXAMPLE_BLOCKED,
                                             "message": None, "error": None, "status": 200}},
                  },
              }}},
        422: {"description": "Invalid quarter format"},
    },
)
def get_npqp(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    quarter: Optional[str] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    anchor = project_anchor(db, project_id)  # quarters are project-start-anchored
    if not quarter:
        qk = quarter_of(_dt_date.today(), anchor)
    else:
        try:
            if "-Q" in quarter.upper():
                qk = parse_quarter_key(quarter, anchor)
            else:
                qk = quarter_of(_dt_date.fromisoformat(quarter), anchor)
        except (ValueError, IndexError) as exc:
            raise ValidationError(
                f"Invalid quarter '{quarter}' — use 'Y1-Q2' or an ISO date.",
                code="invalid_quarter",
            ) from exc

    # Forward caller's JWT to leave-mgmt (JWT-forwarding auth model).
    bearer = None
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            bearer = parts[1].strip() or None
    resp = NpqpService(db).compute(project_id, qk, bearer_token=bearer)
    return api_response(data=resp.model_dump(by_alias=True))
