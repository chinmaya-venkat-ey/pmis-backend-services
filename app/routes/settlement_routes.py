"""Quarterly settlement — audit read + finance override.

Four endpoints, all under /api/v3/sla-compliance/projects/{id}/settlement:

  GET  /                              — list history (all quarters)
  GET  /{quarter}                     — single quarter row (auto-closes lazily)
  POST /{quarter}/mark-invoiced       — lock the row after invoice raise
  POST /{quarter}/override            — finance override (audited)

Auth: standard bearer for GET; POST requires the caller be authenticated
(finer-grained finance permission gate can be added in a follow-up
alongside the svc-npqp hardening).

All responses use the standard api_response envelope:
  {"data": <payload>, "message": null, "error": null, "status": <http>}
On error:
  {"data": null, "message": null,
   "error": {"_type": "Error", "errorIdentifier": "<code>", "message": "..."},
   "status": <http>}
"""
from __future__ import annotations

from datetime import date as _dt_date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
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


class SettlementInvoicedRequest(BaseModel):
    """POST body for `.../settlement/{quarter}/mark-invoiced`."""
    invoice_ref: Optional[str] = Field(
        default=None,
        alias="invoiceRef",
        description="External invoice reference (audit trail).",
        examples=["INV-2026-Q3-001"],
    )

    model_config = {"populate_by_name": True}


router = APIRouter(tags=["sla-settlement"])


# ── OpenAPI response examples ─────────────────────────────────────────
# One canonical settlement row shape — reused by every 200 response.
_SETTLEMENT_ROW_EXAMPLE = {
    "id": "2744efdd-e056-414c-a178-059a690e9c42",
    "projectId": "60c67666-895f-4138-bd99-c907b571e933",
    "contractType": "PMU",
    "fiscalYear": 2026,
    "quarter": 3,
    "quarterStart": "2026-07-01",
    "quarterEnd": "2026-09-30",
    "sumLdPercent": "44.0000",
    "cappedLdPercent": "10.0000",
    "fAmount": "1215801.65",
    "qgrAmount": "0.00",
    "npqp": "1215801.65",
    "ldAmount": "121580.17",
    "paAmount": "1215801.65",
    "aqpAmount": "1094221.49",
    "status": "auto_closed",
    "closedAt": "2026-07-20T08:26:35.442Z",
    "closedBy": "dd9a8a1c-ddb8-4d6f-9259-fb4871b9575b",
    "overrideReason": None,
    "sourceAggregateIds": ["<uuid>", "<uuid>"],
    "consequenceFlags": {},
    "createdAt": "2026-07-20T08:26:35.442Z",
    "updatedAt": "2026-07-20T08:26:35.442Z",
}


def _envelope_ok(data):
    """Wrap an example payload in the api_response envelope shape."""
    return {
        "data": data, "message": None, "error": None, "status": 200,
    }


def _envelope_err(code: str, message: str, status: int = 422):
    return {
        "data": None, "message": None,
        "error": {"_type": "Error", "errorIdentifier": code, "message": message},
        "status": status,
    }


def _bearer_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extract the bearer token from the Authorization header for
    forwarding to leave-mgmt. Returns None when the header is missing
    or malformed."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


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
    description=(
        "Returns every settlement row for the project sorted by "
        "fiscalYear DESC, quarter DESC. Empty items[] when the project "
        "has no quarters closed yet."
    ),
    responses={
        200: {"description": "Envelope with data.items[] of settlement rows",
              "content": {"application/json": {
                  "example": _envelope_ok({
                      "_type": "SettlementListResponse",
                      "projectId": "60c67666-895f-4138-bd99-c907b571e933",
                      "items": [_SETTLEMENT_ROW_EXAMPLE],
                  }),
              }}},
    },
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
        "quarter cap + AQP) and persists a row with status='auto_closed'. "
        "Passing an already-invoiced quarter returns the frozen row.\n\n"
        "quarter format: 2026-Q1 .. 2026-Q4, or any ISO date in the "
        "target quarter."
    ),
    responses={
        200: {"description": "Envelope with data: <settlement row>",
              "content": {"application/json": {
                  "example": _envelope_ok(_SETTLEMENT_ROW_EXAMPLE),
              }}},
        422: {"description": "Invalid quarter format",
              "content": {"application/json": {
                  "example": _envelope_err(
                      "invalid_quarter",
                      "Invalid quarter '2026-Q9' — use '2026-Q2' or an ISO date.",
                  ),
              }}},
    },
)
def get_settlement(
    project_id: str,
    quarter: str,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
):
    qk = _resolve_quarter(quarter)
    svc = QuarterlySettlementService(db)
    existing = svc.repo.get(project_id=project_id, qk=qk)
    if existing is None or existing.status == "open":
        # Forward the caller's JWT so leave-mgmt validates against the
        # actual user, not a service account.
        row = svc.close(
            project_id, qk, mode="auto",
            bearer_token=_bearer_from_header(authorization),
        )
    else:
        row = existing
    return api_response(data=SettlementItem.model_validate(row).model_dump(by_alias=True))


@router.post(
    "/sla-compliance/projects/{project_id}/settlement/{quarter}/mark-invoiced",
    summary="Lock the settlement row after invoice raise (immutable audit)",
    description=(
        "Called by project-mgmt's invoice-raise flow after the LD "
        "deduction has been billed. Once status='invoiced', the override "
        "endpoint refuses further changes — errors have to be corrected "
        "via credit note, not by mutating the settlement row.\n\n"
        "Safe to invoke twice (idempotent)."
    ),
    responses={
        200: {"description": "Envelope with locked settlement row (status='invoiced')",
              "content": {"application/json": {
                  "example": _envelope_ok({
                      **_SETTLEMENT_ROW_EXAMPLE,
                      "status": "invoiced",
                      "overrideReason": "invoiced (ref=INV-2026-Q3-001)",
                  }),
              }}},
        404: {"description": "No settlement row for this quarter yet",
              "content": {"application/json": {
                  "example": _envelope_err(
                      "settlement_not_found",
                      "No settlement row for 60c67... 2026-Q3 — run auto-close first.",
                      status=404,
                  ),
              }}},
    },
)
def mark_settlement_invoiced(
    project_id: str,
    quarter: str,
    payload: SettlementInvoicedRequest,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    qk = _resolve_quarter(quarter)
    svc = QuarterlySettlementService(db)
    row = svc.mark_invoiced(
        project_id, qk,
        invoiced_by=user_id or "",
        invoice_ref=payload.invoice_ref,
    )
    return api_response(data=SettlementItem.model_validate(row).model_dump(by_alias=True))


@router.post(
    "/sla-compliance/projects/{project_id}/settlement/{quarter}/override",
    summary="Finance override — replace sum_ld_percent + recompute",
    description=(
        "Overrides the auto-close sum-of-per-SLA-LD-%. The new value is "
        "capped at the RFP §5.27.6 quarter cap (10% by default, per "
        "contract_ld_rules.quarterly_ld_cap_pct) before persistence.\n\n"
        "Fails 404 if no settlement row exists yet (run auto-close first); "
        "fails 422 if the row is already invoiced (immutable — issue a "
        "credit note instead)."
    ),
    responses={
        200: {"description": "Envelope with recomputed settlement row (status='overridden')",
              "content": {"application/json": {
                  "example": _envelope_ok({
                      **_SETTLEMENT_ROW_EXAMPLE,
                      "sumLdPercent": "15.0000",
                      "cappedLdPercent": "10.0000",
                      "status": "overridden",
                      "overrideReason": "Adjustment agreed with vendor per email 2026-07-20",
                  }),
              }}},
        404: {"description": "No settlement row for this quarter"},
        422: {"description": "Row is invoiced (immutable)",
              "content": {"application/json": {
                  "example": _envelope_err(
                      "settlement_immutable",
                      "Cannot override an invoiced settlement — issue a credit note.",
                  ),
              }}},
    },
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
