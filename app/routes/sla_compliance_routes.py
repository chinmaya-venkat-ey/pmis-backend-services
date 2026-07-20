"""SLA compliance routes — observation input, the daily cron, and the
aggregate reads the dashboard + cost page consume.

Auth: the read/observation routes ride the standard bearer (the service has
no permission gates yet — auth-only, per app/core/rbac.py). The cron route
is machine-to-machine and gated by the ``X-Cron-Secret`` shared secret
instead of a user token (mirrors the dashboard snapshot cron); it forwards
an optional bearer downstream so it can resolve activities from
project-management.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import ForbiddenError, ValidationError
from app.core.response import api_response
from app.dependencies import get_optional_current_user_id
from app.db import get_db
from app.models.sla_evaluation_result import SlaEvaluationResult
from app.schemas.sla_compliance import ObservationRequest
from app.schemas.sla_quarterly_aggregate import (
    QuarterlyAggregateItem,
    QuarterlyAggregateResponse,
)
from app.services.sla_compliance_service import SlaComplianceService
from app.utilities.quarter import parse_quarter_key, quarter_of

router = APIRouter(tags=["sla-compliance"])


# ------------------------------------------------------------------ observation input

@router.post("/sla-compliance/observations", summary="Record an observed SLA value")
def record_observation(
    payload: ObservationRequest,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    row = SlaComplianceService(db).record_observation(
        mapping_id=payload.mapping_id, observed_value=payload.observed_value,
        metric_key=payload.metric_key, period_start=payload.period_start,
        period_end=payload.period_end, note=payload.note, recorded_by=user_id,
    )
    return api_response(data={"id": row.id, "mappingId": row.mapping_id,
                              "observedValue": row.observed_value, "source": row.source})


# ------------------------------------------------------------------ daily cron

@router.post("/sla-compliance/cron/run", summary="Run the daily SLA evaluation (shared-secret)")
def run_daily_sla(
    db: Annotated[Session, Depends(get_db)],
    x_cron_secret: Annotated[Optional[str], Header(alias="X-Cron-Secret")] = None,
):
    expected = (settings.cron_shared_secret or "").strip()
    if not expected or (x_cron_secret or "").strip() != expected:
        raise ForbiddenError("Invalid or missing cron secret.")
    # No bearer needed — activity resolution is DB-direct (cross-schema mirror).
    summary = SlaComplianceService(db).run_daily()
    return api_response(data=summary)


# ------------------------------------------------------------------ manual evaluation
#
# The daily cron requires X-Cron-Secret so schedulers can call it, but that
# locked out admins + the FE. Result: fresh installs showed "0% compliance"
# on the dashboard until the scheduler fired for the first time, and no
# manual "run this now" path existed.
#
# These two endpoints reuse the same evaluate_and_persist path as the cron,
# gated by regular bearer auth. That means:
#   * The FE observation-entry screen can trigger evaluation right after a
#     new observation is recorded (feedback is immediate).
#   * Admins can flush compliance for one mapping / the whole system.
#   * Tests can seed sla_evaluation_result without a shared secret.
# ------------------------------------------------------------------

# ------------------------------------------------------------------ activity completion
#
# Called by project-management when an activity moves to COMPLETED (or
# actual_end_date is set). Runs SLA evaluation for every ACTIVE mapping
# on the activity:
#
#   * fixed_escalation (date-derivable) → auto-evaluate immediately; a
#     row lands in contract.sla_evaluation_results.
#   * point_accumulation / band_accumulation / wac → mark as
#     pending_observation, then email + notify project + activity
#     owners so they know to record the observed value.
#
# Response summarises what happened per mapping so the caller (usually
# project-mgmt) can log it and the FE can display "SLAs evaluated on
# completion" on the activity detail page.
# ------------------------------------------------------------------

@router.post(
    "/sla-compliance/activities/{activity_id}/on-complete",
    summary="Evaluate all SLAs on this activity now (called on completion)",
    description=(
        "Triggered by project-management when the activity moves to "
        "COMPLETED. Auto-evaluates every date-derivable SLA (linear-LD "
        "shape) on the activity, and for each SLA that needs a manual "
        "observation, emails the project + activity owners via the "
        "notification service so they can record the value. Response "
        "returns per-mapping outcomes: autoEvaluated / manualNeeded / "
        "errors. Safe to re-invoke (idempotent on evaluated_on)."
    ),
)
def on_activity_complete(
    activity_id: str,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    summary = SlaComplianceService(db).on_activity_complete(activity_id)
    return api_response(data=summary)


@router.get(
    "/sla-compliance/activities/{activity_id}",
    summary="All SLA evaluation results for one activity",
    description=(
        "Returns every latest-per-mapping row in sla_evaluation_results "
        "that belongs to this activity, plus the summary block used on "
        "the activity detail page (compliance %, met, breached, pending, "
        "excluded, data_state). Empty results list on activities with no "
        "SLA mappings — the summary still returns available:true so the "
        "FE renders 'no SLAs mapped' rather than 'not available'."
    ),
)
def sla_for_activity(
    activity_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    from app.models.sla_evaluation_result import SlaEvaluationResult
    sub = _latest_per_mapping()
    stmt = (
        select(SlaEvaluationResult)
        .join(sub, (SlaEvaluationResult.mapping_id == sub.c.mapping_id)
              & (SlaEvaluationResult.evaluated_on == sub.c.d))
        .where(SlaEvaluationResult.activity_id == activity_id)
    )
    rows = list(db.execute(stmt).scalars().all())
    summary = _summarise(rows)

    def _f(x):
        return float(x) if x is not None else None
    results = [
        {
            "mappingId":         r.mapping_id,
            "slaId":             r.sla_id,
            "slaRef":            r.sla_ref,
            "formulaType":       r.formula_type,
            "evaluatedOn":       r.evaluated_on.isoformat() if r.evaluated_on else None,
            "status":            r.status,
            "met":               r.met,
            "breached":          r.breached,
            "severityLevel":     r.severity_level,
            "accumulatedPoints": _f(r.accumulated_points),
            "targetDays":        _f(r.target_days),
            "actualDays":        _f(r.actual_days),
            "delayDays":         _f(r.delay_days),
            "ldPercent":         _f(r.ld_percent),
            "ldAmount":          _f(r.ld_amount),
            "ldBaseAmount":      _f(r.ld_base_amount),
            "ldBaseKind":        r.ld_base_kind,
            "observedValue":     r.observed_value,
        }
        for r in rows
    ]
    return api_response(data={
        "activityId": activity_id,
        **summary,
        "results":    results,
    })


@router.post(
    "/sla-compliance/evaluate-all",
    summary="Run SLA evaluation across every ACTIVE mapping (admin, auth-required)",
    description=(
        "Same code path as /sla-compliance/cron/run, but gated by the "
        "regular bearer instead of the cron shared secret. Use this to "
        "seed sla_evaluation_result on a fresh deploy or flush after "
        "an SLA config change. Returns a per-status count summary."
    ),
)
def evaluate_all_now(
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    summary = SlaComplianceService(db).run_daily()
    return api_response(data=summary)


@router.post(
    "/sla-compliance/mappings/{mapping_id}/evaluate",
    summary="Evaluate one mapping now (admin, auth-required)",
    description=(
        "Runs evaluate_and_persist for a single mapping — used by the FE "
        "observation-entry screen so recording a value immediately flips "
        "the mapping's compliance status instead of waiting for the cron."
    ),
)
def evaluate_mapping_now(
    mapping_id: str,
    db: Annotated[Session, Depends(get_db)],
    user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    from datetime import datetime, timezone
    status = SlaComplianceService(db).evaluate_and_persist(
        mapping_id, datetime.now(timezone.utc).date(),
    )
    return api_response(data={"mapping_id": mapping_id, "status": status})


# ------------------------------------------------------------------ aggregates

def _latest_per_mapping():
    """Subquery of the newest evaluated_on per mapping (aggregates read the
    most recent result, not the whole history)."""
    return (
        select(SlaEvaluationResult.mapping_id,
               func.max(SlaEvaluationResult.evaluated_on).label("d"))
        .group_by(SlaEvaluationResult.mapping_id).subquery()
    )


def _latest_results(db: Session, *, project_ids: Optional[List[str]] = None) -> List[SlaEvaluationResult]:
    sub = _latest_per_mapping()
    stmt = (
        select(SlaEvaluationResult)
        .join(sub, (SlaEvaluationResult.mapping_id == sub.c.mapping_id)
              & (SlaEvaluationResult.evaluated_on == sub.c.d))
    )
    if project_ids is not None:
        if not project_ids:
            return []
        stmt = stmt.where(SlaEvaluationResult.project_id.in_(project_ids))
    return list(db.execute(stmt).scalars().all())


def _summarise(rows: List[SlaEvaluationResult]) -> Dict[str, Any]:
    """Roll SlaEvaluationResult rows into the dashboard-friendly shape.

    Also emits a ``data_state`` classification so the dashboard can
    distinguish "0% compliant" (real breach) from "no data yet" (nothing
    to compute against). Without this, an empty table reads on the FE
    as "we're failing everything" — misleading enough that users
    called it broken.

    data_state values:
      no_data                — table is empty for this scope
      awaiting_observations  — rows exist but every one is
                                pending_observation / excluded /
                                not_due (met + breached == 0)
      partial                — some rows evaluated, some still pending
      ready                  — every row has flipped to compliant /
                                breached / excluded (nothing pending)
    """
    met      = sum(1 for r in rows if r.met)
    breached = sum(1 for r in rows if r.breached)
    pending  = sum(1 for r in rows if r.status == "pending_observation")
    excluded = sum(1 for r in rows if r.status == "excluded")
    denom    = met + breached
    if not rows:
        data_state = "no_data"
    elif denom == 0:
        data_state = "awaiting_observations"
    elif pending > 0:
        data_state = "partial"
    else:
        data_state = "ready"
    return {
        "available":  True,
        "data_state": data_state,
        # ``None`` when there's nothing to divide against — the FE renders
        # a "No SLA data yet" banner instead of "0% compliance".
        "compliance": round(met * 100 / denom) if denom else None,
        "met":        met,
        "breached":   breached,
        "evaluated":  len(rows),
        "pending":    pending,
        "excluded":   excluded,
    }


@router.get("/sla-compliance/summary", summary="Global SLA compliance")
def sla_summary(db: Annotated[Session, Depends(get_db)]):
    return api_response(data=_summarise(_latest_results(db)))


@router.get("/sla-compliance/projects/{project_id}", summary="Per-project SLA compliance + breaches")
def sla_for_project(project_id: str, db: Annotated[Session, Depends(get_db)]):
    rows = _latest_results(db, project_ids=[project_id])
    out = _summarise(rows)
    # A2 audit fix — surface severity_level, accumulated_points, and the
    # underlying formula_type on every breach row so the FE cost /
    # compliance detail views don't render blank cells for those columns.
    # Every field is guarded against NULL (fixed_escalation rows written
    # before commit 7912946 still have None severity_level even after the
    # 2026-07-17 backfill).
    def _f(x):
        return float(x) if x is not None else None
    out["breaches"] = [
        {
            "activityId":        r.activity_id,
            "milestoneId":       r.milestone_id,
            "slaRef":            r.sla_ref,
            "slaId":             r.sla_id,
            "formulaType":       r.formula_type,
            "sla":               _f(r.target_days),
            "actual":            _f(r.actual_days),
            "delay":             _f(r.delay_days),
            "severityLevel":     r.severity_level,
            "accumulatedPoints": _f(r.accumulated_points),
            "ldPercent":         _f(r.ld_percent),
            "ldAmount":          _f(r.ld_amount),
            "ldBaseAmount":      _f(r.ld_base_amount),
            "ldBaseKind":        r.ld_base_kind,
            "observedValue":     r.observed_value,
            "status":            r.status,
        }
        for r in rows if r.breached
    ]
    return api_response(data=out)


@router.get("/sla-compliance/projects/{project_id}/milestones",
            summary="Per-milestone SLA compliance + LD% (for the cost page)")
def sla_by_milestone(project_id: str, db: Annotated[Session, Depends(get_db)]):
    rows = _latest_results(db, project_ids=[project_id])
    # activity-level capped LD first (engine caps each activity's total at 10%),
    # then sum activities within a milestone.
    from collections import defaultdict
    act_ld: Dict[str, float] = defaultdict(float)
    ms_rows: Dict[str, List[SlaEvaluationResult]] = defaultdict(list)
    for r in rows:
        ms = r.milestone_id or ""
        ms_rows[ms].append(r)
        if r.ld_percent:
            act_ld[(ms, r.activity_id)] = min(10.0, act_ld[(ms, r.activity_id)] + float(r.ld_percent))
    out: Dict[str, Any] = {}
    for ms, rs in ms_rows.items():
        s = _summarise(rs)
        ld = round(sum(v for (m, _a), v in act_ld.items() if m == ms), 4)
        out[ms] = {**s, "ldPercent": ld}
    return api_response(data=out)


@router.get("/sla-compliance/by-project", summary="Compliance for a set of projects (bulk, for org rollup)")
def sla_by_project(db: Annotated[Session, Depends(get_db)],
                   project_ids: Annotated[Optional[str], Header(alias="X-Project-Ids")] = None):
    ids = [p for p in (project_ids or "").split(",") if p] or None
    rows = _latest_results(db, project_ids=ids)
    by: Dict[str, List[SlaEvaluationResult]] = {}
    for r in rows:
        by.setdefault(r.project_id or "", []).append(r)
    return api_response(data={pid: _summarise(rs) for pid, rs in by.items()})


# ------------------------------------------------------------------ Phase B quarterly aggregate
#
# Reads the sla_quarterly_aggregate table (populated by the daily cron and
# by evaluate_and_persist as a side effect). Used by the settlement page
# to show "what did each SLA contribute to this quarter's LD %?" and by
# Phase D's QuarterlySettlementService.close as its input.
#
# `quarter` accepts either "2026-Q2" (label form) or an ISO date (any day
# in the target quarter). Omitted → the quarter containing today.
# ------------------------------------------------------------------

@router.get(
    "/sla-compliance/projects/{project_id}/quarterly-aggregate",
    summary="Per-SLA quarterly aggregate for one project × one quarter",
    description=(
        "Returns every SLA's contribution to this quarter — one row per "
        "(mapping, quarter) with accumulated points, derived severity, "
        "LD %, and audit trail. The endpoint refreshes the rollup "
        "before responding (idempotent, cheap upserts). "
        "`totalLdPercentUncapped` is the sum-of-per-SLA-LD-%s BEFORE "
        "the 10%-NPQP quarter cap; the settlement endpoint applies "
        "the cap.\n\n"
        "Response envelope: standard api_response wrapper."
    ),
    response_model=None,
    responses={
        200: {"description": "Envelope with per-SLA aggregate items",
              "content": {"application/json": {"example": {
                  "data": {
                      "projectId": "60c67666-895f-4138-bd99-c907b571e933",
                      "quarterKey": "2026-Q3",
                      "fiscalYear": 2026, "quarter": 3,
                      "quarterStart": "2026-07-01", "quarterEnd": "2026-09-30",
                      "totalLdPercentUncapped": "44.0000",
                      "items": [{
                          "id": "<uuid>",
                          "mappingId": "<uuid>",
                          "slaId": "<uuid>",
                          "slaRef": "PMU-SLA007",
                          "projectId": "60c67...",
                          "activityId": "<uuid>",
                          "fiscalYear": 2026, "quarter": 3,
                          "quarterStart": "2026-07-01", "quarterEnd": "2026-09-30",
                          "accumulatedPoints": "8.0000",
                          "derivedSeverity": 4,
                          "ldPercent": "4.0000",
                          "carriedForward": False,
                          "sourceResultIds": ["<uuid>"],
                          "notes": {"sourceRowCount": 3},
                          "computedAt": "2026-07-20T08:30:00Z",
                      }],
                  },
                  "message": None, "error": None, "status": 200,
              }}}},
        422: {"description": "Invalid quarter format"},
    },
)
def sla_quarterly_aggregate(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    quarter: Optional[str] = None,   # ?quarter=2026-Q2 or ?quarter=2026-05-10
):
    from datetime import date as _dt_date
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

    svc = SlaComplianceService(db)
    # Refresh first so the response reflects the latest evaluation rows —
    # cheap because upsert-by-primary-key is fast.
    svc.rollup_project_for_quarter(project_id, qk)
    rows = svc.qtr_agg_repo.list_for_project_quarter(project_id=project_id, qk=qk)

    from decimal import Decimal as _D
    from app.models.sla_definition import SlaDefinition
    from app.services.quarterly_settlement_service import _TRACK_B_RULES

    # Batch-load ld_formula_rule per SLA so each item can surface its Track.
    sla_ids = {r.sla_id for r in rows}
    rule_by_sla = {}
    if sla_ids:
        for sid, rule in db.execute(
            select(SlaDefinition.id, SlaDefinition.ld_formula_rule)
            .where(SlaDefinition.id.in_(list(sla_ids)))
        ).all():
            rule_by_sla[sid] = rule

    def _make_item(r):
        item = QuarterlyAggregateItem.model_validate(r)
        rule = rule_by_sla.get(r.sla_id)
        item.ld_formula_rule = rule
        if rule is None:
            item.ld_track = None
        elif rule in _TRACK_B_RULES:
            item.ld_track = "B"
        else:
            item.ld_track = "A"
        return item

    # Uncapped total sums ONLY Track B — Track A doesn't contribute to
    # the NPQP-cap math (per RFP §5.28.2 vs §5.28.3 separation).
    uncapped = sum(
        (r.ld_percent or _D("0")) for r in rows
        if (rule_by_sla.get(r.sla_id) or "LADDER") in _TRACK_B_RULES
    ) or _D("0")

    resp = QuarterlyAggregateResponse(
        project_id=project_id,
        quarter_key=qk.label(),
        fiscal_year=qk.fiscal_year,
        quarter=qk.quarter,
        quarter_start=qk.quarter_start,
        quarter_end=qk.quarter_end,
        total_ld_percent_uncapped=uncapped,
        items=[_make_item(r) for r in rows],
    )
    return api_response(data=resp.model_dump(by_alias=True))
