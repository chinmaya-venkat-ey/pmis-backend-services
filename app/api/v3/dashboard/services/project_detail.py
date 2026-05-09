"""``GET /api/v3/dashboard/projects/{id}`` — Project View payload.

Returns:
  * Project header card (the same ``ProjectCard`` shape as the listing).
  * Five KPI tiles (Overall Progress, Milestones, Activities,
    Pending Approvals — static 0 in v1, Delayed).
  * Project pie counts (M/A items only — three buckets).
  * Delayed track rows (M/A items above the delay floor with their
    ``daysDelayed`` value).
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....shared.dashboard_derive import (
    BUCKET_DELAYED,
    BUCKET_COMPLETED,
    BUCKET_ONTRACK,
    PROJECT_BUCKETS,
    ist_today,
    item_bucket,
    item_delay_days,
)
from .....shared.datetime import iso_ist
from .common import build_project_card, vendor_chips


# Pending approvals KPI is intentionally static at zero — approval
# workflow is deferred to the next phase.
_STATIC_PENDING_APPROVALS = 0


def get_project_detail(
    db: Session,
    *,
    project_id: str,
    delay_min_days: int = 5,
) -> Dict:
    repo = DashboardRepository(db)
    today = ist_today()

    projects = repo.list_live_projects(ids=[project_id])
    if not projects:
        raise NotFoundError("The project could not be found.")
    project = projects[0]

    counters = repo.fetch_per_project_counters(
        project_ids=[project_id], today_ist=today,
    )[project_id]
    vendors = repo.fetch_vendors_for_projects(
        project_ids=[project_id],
    ).get(project_id, [])
    progress_pct, bucket = repo.derive_progress_and_bucket(
        counters=counters, lifecycle_status=project.status,
    )

    # ---- Card --------------------------------------------------------
    card = build_project_card(
        project=project,
        counters=counters,
        vendors=vendors,
        progress_pct=progress_pct,
        bucket=bucket,
    )

    # ---- Five KPI tiles ---------------------------------------------
    kpis = {
        "progressPct": progress_pct,
        "milestonesTotal": counters["milestonesTotal"],
        "milestonesCompleted": counters["milestonesCompleted"],
        "milestonesDelayed": counters["milestonesDelayed"],
        "milestonesOntrack": counters["milestonesOntrack"],
        "activitiesTotal": counters["activitiesTotal"],
        "activitiesCompleted": counters["activitiesCompleted"],
        "activitiesDelayed": counters["activitiesDelayed"],
        "activitiesOntrack": counters["activitiesOntrack"],
        "pendingApprovals": _STATIC_PENDING_APPROVALS,
        "delayedCount": counters["delayedItemCount"],
    }

    # ---- Pie counts over M/A items only -----------------------------
    pie = {
        "total": counters["milestonesTotal"] + counters["activitiesTotal"],
        "ontrack": counters["milestonesOntrack"] + counters["activitiesOntrack"],
        "delayed": counters["milestonesDelayed"] + counters["activitiesDelayed"],
        "completed": (
            counters["milestonesCompleted"] + counters["activitiesCompleted"]
        ),
    }

    # ---- Delayed track rows -----------------------------------------
    # Walk the same milestone + activity rows we counted above and emit
    # those whose own delay >= floor.
    delayed_rows: List[Dict] = []

    # Pre-fetch milestones for WBS labels + names (used by activity rows
    # for the contextual "milestone" cell).
    milestone_rows = repo.fetch_milestone_rows(project_id=project_id)
    m_index_by_id: Dict[str, int] = {}
    m_name_by_id: Dict[str, str] = {}
    for idx, m in enumerate(milestone_rows, start=1):
        mid = m[0]
        m_index_by_id[mid] = idx
        m_name_by_id[mid] = m[1]

    for idx, m in enumerate(milestone_rows, start=1):
        (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
        b = item_bucket(mstatus, mend, today)
        if b != BUCKET_DELAYED:
            continue
        d = item_delay_days(mstatus, mend, today)
        if d < delay_min_days:
            continue
        delayed_rows.append({
            "id": mid,
            "kind": "milestone",
            "wbs": f"M{idx}",
            "name": mname,
            "milestoneId": None,
            "milestoneName": None,
            "plannedStart": iso_ist(mstart),
            "plannedEnd": iso_ist(mend),
            "actualStart": iso_ist(mas),
            "actualEnd": iso_ist(mae),
            "daysDelayed": d,
        })

    # Walk activities — group by milestone for the WBS index.
    activity_rows = repo.fetch_activity_rows(project_id=project_id)
    activity_index_per_milestone: Dict[str, int] = {}
    for a in activity_rows:
        (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
        activity_index_per_milestone[amid] = (
            activity_index_per_milestone.get(amid, 0) + 1
        )
        ai = activity_index_per_milestone[amid]
        mi = m_index_by_id.get(amid, 0)
        b = item_bucket(astatus, aend, today)
        if b != BUCKET_DELAYED:
            continue
        d = item_delay_days(astatus, aend, today)
        if d < delay_min_days:
            continue
        delayed_rows.append({
            "id": aid,
            "kind": "activity",
            "wbs": f"A{mi}.{ai}",
            "name": aname,
            "milestoneId": amid,
            "milestoneName": m_name_by_id.get(amid),
            "plannedStart": iso_ist(astart),
            "plannedEnd": iso_ist(aend),
            "actualStart": iso_ist(aas),
            "actualEnd": iso_ist(aae),
            "daysDelayed": d,
        })

    # Sort by days delayed desc — most-delayed first.
    delayed_rows.sort(key=lambda r: -r["daysDelayed"])

    return {
        "asOf": today.isoformat(),
        "delayMinDays": delay_min_days,
        "project": card,
        "kpis": kpis,
        "pie": pie,
        "delayedTrack": delayed_rows,
    }
