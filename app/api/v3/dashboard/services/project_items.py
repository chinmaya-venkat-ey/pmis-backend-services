"""``GET /api/v3/dashboard/projects/{id}/items`` — drill-down rows.

Returns milestone and / or activity rows under a project, optionally
filtered by ``kind`` (``milestone`` | ``activity``), ``bucket``, a
specific milestone, and a delay floor. Used by every "click on a KPI
tile" path on the Project View screen.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....infrastructure.db.repositories.project_repository import (
    ProjectRepository,
)
from .....shared.dashboard_derive import (
    BUCKET_COMPLETED,
    BUCKET_DELAYED,
    BUCKET_ONTRACK,
    ITEM_BUCKETS,
    ist_today,
    item_bucket,
    item_delay_days,
    progress_pct,
)
from .....shared.datetime import iso_ist


_VALID_KINDS = {"milestone", "activity"}


def get_project_items(
    db: Session,
    *,
    project_id: str,
    kind: Optional[str] = None,
    bucket: Optional[str] = None,
    milestone_id: Optional[str] = None,
    min_delay: Optional[int] = None,
) -> Dict:
    if not ProjectRepository(db).exists_by_id(project_id):
        raise NotFoundError("The project could not be found.")

    if kind is not None and kind not in _VALID_KINDS:
        kind = None
    if bucket is not None and bucket not in set(ITEM_BUCKETS):
        bucket = None

    repo = DashboardRepository(db)
    today = ist_today()

    rows: List[Dict] = []

    # Pre-fetch milestones once — needed for both the milestone rows and
    # the activity rows' WBS context.
    milestone_rows = repo.fetch_milestone_rows(project_id=project_id)
    m_index_by_id: Dict[str, int] = {}
    m_name_by_id: Dict[str, str] = {}
    for idx, m in enumerate(milestone_rows, start=1):
        m_index_by_id[m[0]] = idx
        m_name_by_id[m[0]] = m[1]

    # Activities are needed for milestone progress rollups even if the
    # caller asked for milestones only.
    activity_rows = repo.fetch_activity_rows(
        project_id=project_id,
        milestone_id=milestone_id,
    )
    # Group activities by milestone for the WBS index + the progress
    # rollup on milestone rows.
    activities_by_milestone: Dict[str, List] = {}
    activity_index_per_milestone: Dict[str, int] = {}
    for a in activity_rows:
        amid = a[1]
        activities_by_milestone.setdefault(amid, []).append(a)

    # ---- Milestones ------------------------------------------------------
    if kind in (None, "milestone"):
        for idx, m in enumerate(milestone_rows, start=1):
            (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
            if milestone_id is not None and mid != milestone_id:
                continue
            b = item_bucket(mstatus, mend, today)
            d = item_delay_days(mstatus, mend, today)
            if bucket is not None and b != bucket:
                continue
            if min_delay is not None and d < min_delay:
                continue
            # Milestone progress = % of its activities currently
            # ``status=completed`` over its total live activities.
            children = activities_by_milestone.get(mid, [])
            child_completed = sum(
                1 for c in children if (c[4] or "") == "completed"
            )
            mp = progress_pct(child_completed, len(children))
            rows.append({
                "id": mid,
                "kind": "milestone",
                "wbs": f"M{idx}",
                "name": mname,
                "milestoneId": None,
                "milestoneName": None,
                "status": mstatus,
                "bucket": b,
                "plannedStart": iso_ist(mstart),
                "plannedEnd": iso_ist(mend),
                "actualStart": iso_ist(mas),
                "actualEnd": iso_ist(mae),
                "daysDelayed": d,
                "progressPct": mp,
            })

    # ---- Activities ------------------------------------------------------
    if kind in (None, "activity"):
        for a in activity_rows:
            (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
            activity_index_per_milestone[amid] = (
                activity_index_per_milestone.get(amid, 0) + 1
            )
            ai = activity_index_per_milestone[amid]
            mi = m_index_by_id.get(amid, 0)
            b = item_bucket(astatus, aend, today)
            d = item_delay_days(astatus, aend, today)
            if bucket is not None and b != bucket:
                continue
            if min_delay is not None and d < min_delay:
                continue
            rows.append({
                "id": aid,
                "kind": "activity",
                "wbs": f"A{mi}.{ai}",
                "name": aname,
                "milestoneId": amid,
                "milestoneName": m_name_by_id.get(amid),
                "status": astatus,
                "bucket": b,
                "plannedStart": iso_ist(astart),
                "plannedEnd": iso_ist(aend),
                "actualStart": iso_ist(aas),
                "actualEnd": iso_ist(aae),
                "daysDelayed": d,
                "progressPct": 100 if (astatus or "") == "completed" else 0,
            })

    counts = {"total": len(rows), "ontrack": 0, "delayed": 0, "completed": 0}
    for r in rows:
        b = r["bucket"]
        if b in counts:
            counts[b] += 1

    return {
        "asOf": today.isoformat(),
        "counts": counts,
        "rows": rows,
    }
