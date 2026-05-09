"""Organization view endpoints.

  * ``GET /api/v3/dashboard/organisations`` — full vendor grid +
    active/inactive vendor pie.
  * ``GET /api/v3/dashboard/organisations/{vendorId}`` — vendor detail
    page with project list + KPI counts + project pie.

A vendor that is soft-deleted (``vendors.deleted_at IS NOT NULL``) is
hidden from both endpoints. A vendor that is live but inactive
(``active=False``) is included — the FE renders inactive vendors with
an ``inactive`` chip; the pie counts them as ``inactiveVendors``.
"""
from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....shared.dashboard_derive import ist_today
from .common import (
    build_bucket_counts,
    build_project_card,
    fetch_projects_with_buckets,
)


def list_organisations(db: Session) -> Dict:
    repo = DashboardRepository(db)
    today = ist_today()

    vendors = repo.list_live_vendors()

    # Per-vendor project counts: walk live projects once, fold buckets
    # by attached vendor.
    projects, counters, vendors_by_pid, derived = fetch_projects_with_buckets(
        repo=repo, today_ist=today,
    )

    vendor_to_buckets: Dict[str, List[str]] = defaultdict(list)
    for p in projects:
        b = derived[p.id][1]
        for vid, _vname, _vactive in vendors_by_pid.get(p.id, []):
            vendor_to_buckets[vid].append(b)

    org_cards: List[Dict] = []
    active_count = 0
    inactive_count = 0
    for v in vendors:
        if v.active:
            active_count += 1
        else:
            inactive_count += 1
        buckets = vendor_to_buckets.get(v.id, [])
        org_cards.append({
            "id": v.id,
            "name": v.name,
            "active": bool(v.active),
            "projectCount": len(buckets),
            "counts": build_bucket_counts(buckets),
        })
    # Sort: active first, then by project count desc, then name.
    org_cards.sort(
        key=lambda c: (not c["active"], -c["projectCount"], c["name"]),
    )

    return {
        "asOf": today.isoformat(),
        "pie": {
            "activeVendors": active_count,
            "inactiveVendors": inactive_count,
            "total": active_count + inactive_count,
        },
        "organisations": org_cards,
    }


def get_organisation_detail(db: Session, *, vendor_id: str) -> Dict:
    repo = DashboardRepository(db)
    today = ist_today()

    vendor = repo.get_vendor(vendor_id)
    if vendor is None:
        raise NotFoundError("The organisation could not be found.")

    project_ids = repo.fetch_project_ids_for_vendor(vendor_id)
    projects, counters, vendors_by_pid, derived = fetch_projects_with_buckets(
        repo=repo, today_ist=today, project_ids=project_ids,
    )

    cards = [
        build_project_card(
            project=p,
            counters=counters[p.id],
            vendors=vendors_by_pid.get(p.id, []),
            progress_pct=derived[p.id][0],
            bucket=derived[p.id][1],
        )
        for p in projects
    ]

    bucket_list = [derived[p.id][1] for p in projects]
    pie = build_bucket_counts(bucket_list)

    return {
        "asOf": today.isoformat(),
        "organisation": {
            "id": vendor.id,
            "name": vendor.name,
            "active": bool(vendor.active),
            "projectCount": len(projects),
            "counts": pie,
        },
        "pie": pie,
        "projects": cards,
    }
