"""Shared helpers used across the dashboard service layer.

The dashboard composes a few card shapes repeatedly (a project card,
a vendor chip list, bucket counts). Putting the shaping in one place
keeps the per-endpoint services thin.
"""
from datetime import date as _date
from typing import Dict, List, Tuple

from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....shared.datetime import iso_ist


# Division code → display label. Backend stores codes (tmd1/tmd2/others);
# the dashboard renders the human label. ``others`` projects also carry
# a free-text label in ``owner_other`` which is included on the card —
# but for grouping we use the catalog code.
_DIVISION_LABELS = {
    "tmd1": "TMD-I",
    "tmd2": "TMD-II",
    "others": "Others",
}


def division_label(code: str) -> str:
    """Human label for a division code. Falls back to the code itself
    if the catalog grows beyond the known three."""
    if not code:
        return "—"
    return _DIVISION_LABELS.get(code.lower(), code)


def vendor_chip(vendor_id: str, vendor_name: str, active: bool) -> Dict:
    """A single ``{id, name, active}`` chip — matches the ``VendorChip``
    schema."""
    return {"id": vendor_id, "name": vendor_name, "active": bool(active)}


def vendor_chips(rows: List[Tuple[str, str, bool]]) -> List[Dict]:
    """Map ``[(vendor_id, vendor_name, active), ...]`` → chip dicts."""
    return [vendor_chip(*r) for r in rows]


def build_project_card(
    *,
    project: ProjectModel,
    counters: Dict,
    vendors: List[Tuple[str, str, bool]],
    progress_pct: int,
    bucket: str,
) -> Dict:
    """Compose the dict that matches the ``ProjectCard`` schema.

    The caller supplies the pre-computed ``counters`` dict (from
    ``DashboardRepository.fetch_per_project_counters``), the vendor
    triples (from ``fetch_vendors_for_projects``), and the derived
    progress + bucket. This function just shapes the wire payload.
    """
    return {
        "id": project.id,
        "projectCode": project.project_code,
        "name": project.name,
        "description": project.description,
        "organisations": vendor_chips(vendors),
        "division": project.owner,
        "divisionOther": project.owner_other,
        "lifecycleStatus": project.status,
        "bucket": bucket,
        "progressPct": progress_pct,
        "plannedStart": iso_ist(project.start_date),
        "plannedEnd": iso_ist(project.end_date),
        "actualStart": iso_ist(project.actual_start_date),
        "actualEnd": iso_ist(project.actual_end_date),
        "milestonesTotal": counters["milestonesTotal"],
        "milestonesCompleted": counters["milestonesCompleted"],
        "activitiesTotal": counters["activitiesTotal"],
        "activitiesCompleted": counters["activitiesCompleted"],
        "delayedItemCount": counters["delayedItemCount"],
        "maxDelayDays": counters["maxDelayDays"],
    }


def build_bucket_counts(buckets: List[str]) -> Dict[str, int]:
    """Fold a list of bucket strings into the ``BucketCounts`` shape."""
    out = {"total": 0, "ontrack": 0, "delayed": 0, "completed": 0}
    for b in buckets:
        out["total"] += 1
        if b in out:
            out[b] += 1
    return out


def fetch_projects_with_buckets(
    *,
    repo: DashboardRepository,
    today_ist: _date,
    project_ids: List[str] = None,
):
    """One-stop fetch + derive: returns
    ``(projects, counters_by_pid, vendors_by_pid, derived_by_pid)``
    where ``derived_by_pid[pid] == (progressPct, bucket)``.

    Used by the summary, project list, and organisation pages — they
    all need the same join. ``project_ids`` filters the project set;
    pass ``None`` for "every live project".
    """
    if project_ids is None:
        projects = repo.list_live_projects()
    else:
        projects = repo.list_live_projects(ids=project_ids)
    pids = [p.id for p in projects]
    counters = repo.fetch_per_project_counters(
        project_ids=pids, today_ist=today_ist,
    )
    vendors_by_pid = repo.fetch_vendors_for_projects(project_ids=pids)
    derived: Dict[str, Tuple[int, str]] = {}
    for p in projects:
        derived[p.id] = repo.derive_progress_and_bucket(
            counters=counters[p.id], lifecycle_status=p.status,
        )
    return projects, counters, vendors_by_pid, derived
