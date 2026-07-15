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
from app.core.errors import ForbiddenError
from app.core.response import api_response
from app.dependencies import get_optional_current_user_id
from app.db import get_db
from app.models.sla_evaluation_result import SlaEvaluationResult
from app.schemas.sla_compliance import ObservationRequest
from app.services.sla_compliance_service import SlaComplianceService

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
    out["breaches"] = [
        {"activityId": r.activity_id, "milestoneId": r.milestone_id, "slaRef": r.sla_ref,
         "sla": float(r.target_days) if r.target_days is not None else None,
         "actual": float(r.actual_days) if r.actual_days is not None else None,
         "delay": float(r.delay_days) if r.delay_days is not None else None,
         "ldPercent": float(r.ld_percent) if r.ld_percent is not None else None,
         "ldAmount": float(r.ld_amount) if r.ld_amount is not None else None,
         "status": r.status}
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
