"""Quarterly settlement — audit read + finance override.

Three endpoints, all under /api/v3/sla-compliance/projects/{id}/settlement:

  GET  /                              — list history (all quarters)
  GET  /{quarter}                     — single quarter row (auto-closes lazily)
  POST /{quarter}/override            — finance override (audited)

Auth: standard bearer for GET; POST requires the caller be authenticated
(finer-grained finance permission gate can be added in a follow-up
alongside the svc-npqp hardening).
"""
from __future__ import annotations

from datetime import date as _dt_date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.response import api_response
from app.db import get_db
from app.dependencies import get_optional_current_user_id
from app.schemas.sla_settlement import (
    SettlementItem,
    SettlementListResponse,
    SettlementOverrideRequest,
)
from app.services.quarterly_settlement_service import QuarterlySettlementService
from app.utilities.quarter import parse_quarter_key, quarter_of


router = APIRouter(tags=["sla-settlement"])


def _resolve_quarter(quarter: Optional[str]):
    if not quarter:
        return quarter_of(_dt_date.today())
    try:
        if "-Q" in quarter.upper():
            return parse_quarter_key(quarter)
        return quarter_of(_dt_date.fromisoformat(quarter))
    except (ValueError, IndexError) as exc:
        raise ValidationError(
            f"Invalid quarter '{quarter}' — use '2026-Q2' or an ISO date.",
            code="invalid_quarter",
        ) from exc


@router.get(
    "/sla-compliance/projects/{project_id}/settlement",
    summary="List every settlement row for this project (history)",
)
def list_settlements(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    svc = QuarterlySettlementService(db)
    rows = svc.repo.list_for_project(project_id)
    resp = SettlementListResponse(
        project_id=project_id,
        items=[SettlementItem.model_validate(r) for r in rows],
    )
    return api_response(data=resp.model_dump(by_alias=True))


@router.get(
    "/sla-compliance/projects/{project_id}/settlement/{quarter}",
    summary="One settlement row (auto-closes on first read if missing)",
    description=(
        "Reads the settlement for the given quarter. If none exists, "
        "runs the close computation (Phase B rollup + Phase C NPQP + "
        "cap + AQP) and persists a row with status='auto_closed'. "
        "Passing an already-invoiced quarter returns the frozen row."
    ),
)
def get_settlement(
    project_id: str,
    quarter: str,
    db: Annotated[Session, Depends(get_db)],
):
    qk = _resolve_quarter(quarter)
    svc = QuarterlySettlementService(db)
    existing = svc.repo.get(project_id=project_id, qk=qk)
    if existing is None or existing.status == "open":
        # Compute + persist on demand.
        row = svc.close(project_id, qk, mode="auto")
    else:
        row = existing
    return api_response(data=SettlementItem.model_validate(row).model_dump(by_alias=True))


@router.post(
    "/sla-compliance/projects/{project_id}/settlement/{quarter}/override",
    summary="Finance override — replace sum_ld_percent + recompute",
    description=(
        "Overrides the auto-close sum-of-per-SLA-LD-%. The new value is "
        "capped at 10% × NPQP per RFP §5.27.6 before persistence. "
        "Fails 404 if no settlement row exists yet (run auto-close first); "
        "fails 422 if the row is already invoiced (immutable — issue a "
        "credit note instead)."
    ),
)
def override_settlement(
    project_id: str,
    quarter: str,
    payload: SettlementOverrideRequest,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    qk = _resolve_quarter(quarter)
    svc = QuarterlySettlementService(db)
    row = svc.override(
        project_id, qk,
        new_sum_ld_percent=payload.sum_ld_percent,
        override_reason=payload.override_reason,
        closed_by=user_id or "",
    )
    return api_response(data=SettlementItem.model_validate(row).model_dump(by_alias=True))
