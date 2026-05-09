"""``GET /api/v3/dashboard/projects`` — paginated project cards with
optional bucket / search / vendor / division filters.

Used by the FE in two places:
  * Project picker dropdown (pulls every live project).
  * Project listing pages opened from a Summary KPI tile (filtered by
    bucket).
"""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....shared.dashboard_derive import (
    BUCKET_COMPLETED,
    BUCKET_DELAYED,
    BUCKET_ONTRACK,
    PROJECT_BUCKETS,
    ist_today,
)
from .common import (
    build_bucket_counts,
    build_project_card,
    fetch_projects_with_buckets,
)


_VALID_BUCKETS = set(PROJECT_BUCKETS) | {"total", "active"}


def _matches_filters(
    *,
    project,
    counters: Dict,
    vendors,
    progress_pct: int,
    bucket: str,
    bucket_filter: Optional[str],
    q: Optional[str],
    vendor_id: Optional[str],
    division: Optional[str],
) -> bool:
    # Bucket filter: ``total`` and ``None`` both pass; ``active`` means
    # not-completed; otherwise an exact bucket match.
    if bucket_filter and bucket_filter != "total":
        if bucket_filter == "active":
            if bucket == BUCKET_COMPLETED:
                return False
        elif bucket != bucket_filter:
            return False

    # Free-text search across id / projectCode / name / division /
    # vendor names.
    if q:
        needle = q.lower()
        haystack_parts = [
            project.id,
            project.project_code or "",
            project.name or "",
            project.owner or "",
            project.owner_other or "",
        ]
        haystack_parts.extend([v[1] for v in vendors])  # vendor names
        if not any(needle in (p or "").lower() for p in haystack_parts):
            return False

    if vendor_id:
        if not any(v[0] == vendor_id for v in vendors):
            return False

    if division:
        target = division.lower()
        if (project.owner or "").lower() != target:
            return False

    return True


def list_dashboard_projects(
    db: Session,
    *,
    bucket: Optional[str] = None,
    q: Optional[str] = None,
    vendor_id: Optional[str] = None,
    division: Optional[str] = None,
    page: int = 1,
    page_size: int = 200,
) -> Dict:
    if bucket is not None and bucket not in _VALID_BUCKETS:
        # Treat unknown filter as "no filter" — keeps the route gentle.
        # The route layer can add a stricter guard later if we expose
        # it as documented.
        bucket = None

    if page < 1:
        page = 1
    page_size = max(1, min(page_size, 500))

    repo = DashboardRepository(db)
    today = ist_today()
    projects, counters, vendors_by_pid, derived = fetch_projects_with_buckets(
        repo=repo, today_ist=today,
    )

    # Filter step.
    matched = []
    for p in projects:
        prog, b = derived[p.id]
        if _matches_filters(
            project=p,
            counters=counters[p.id],
            vendors=vendors_by_pid.get(p.id, []),
            progress_pct=prog,
            bucket=b,
            bucket_filter=bucket,
            q=q,
            vendor_id=vendor_id,
            division=division,
        ):
            matched.append(p)

    # Counts over the FILTERED set so the FE can render the small pie
    # next to the listing.
    counts = build_bucket_counts([derived[p.id][1] for p in matched])

    # Pagination.
    total = len(matched)
    start = (page - 1) * page_size
    end = start + page_size
    page_projects = matched[start:end]

    cards = [
        build_project_card(
            project=p,
            counters=counters[p.id],
            vendors=vendors_by_pid.get(p.id, []),
            progress_pct=derived[p.id][0],
            bucket=derived[p.id][1],
        )
        for p in page_projects
    ]

    return {
        "asOf": today.isoformat(),
        "page": page,
        "pageSize": page_size,
        "total": total,
        "counts": counts,
        "projects": cards,
    }
