"""``GET /api/v3/dashboard/summary`` — Summary view payload.

Composes:
  * Global project bucket counts (for the pie + KPI strip).
  * Top-N delayed projects (one row per project, with item count + max
    delay days).
  * Top-N vendor cards (Organization view's preview).
  * Top-N division cards (Division view's preview).

All counts exclude soft-deleted projects, soft-deleted M/A, and
catalog-deleted vendors. The "delay floor" defaults to 5 days.
"""
from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.dashboard_repository import (
    DashboardRepository,
)
from .....shared.dashboard_derive import ist_today
from .common import (
    build_bucket_counts,
    division_label,
    fetch_projects_with_buckets,
    vendor_chips,
)


def get_summary(
    db: Session,
    *,
    delay_min_days: int = 5,
    top_delayed: int = 4,
    top_orgs: int = 3,
    top_divisions: int = 3,
) -> Dict:
    repo = DashboardRepository(db)
    today = ist_today()

    projects, counters, vendors_by_pid, derived = fetch_projects_with_buckets(
        repo=repo, today_ist=today,
    )

    # ---- KPI strip / pie counts -------------------------------------------
    all_buckets = [derived[p.id][1] for p in projects]
    counts = build_bucket_counts(all_buckets)

    # ---- Delayed track (one row per project, sorted by item count desc) ----
    delayed_rows: List[Dict] = []
    for p in projects:
        c = counters[p.id]
        # Floor on max delay days — only include projects whose worst
        # item is delayed by at least delay_min_days. Counts every
        # delayed item in that project, not just the worst one.
        if c["delayedItemCount"] <= 0 or c["maxDelayDays"] < delay_min_days:
            continue
        delayed_rows.append({
            "id": p.id,
            "projectCode": p.project_code,
            "name": p.name,
            "organisations": vendor_chips(vendors_by_pid.get(p.id, [])),
            "division": p.owner,
            "divisionOther": p.owner_other,
            "delayedItemCount": c["delayedItemCount"],
            "maxDelayDays": c["maxDelayDays"],
        })
    delayed_rows.sort(
        key=lambda r: (r["delayedItemCount"], r["maxDelayDays"]),
        reverse=True,
    )
    delayed_top = delayed_rows[:top_delayed] if top_delayed else delayed_rows

    # ---- Organisation cards (top-N by project count) ---------------------
    # Map vendor → list of project buckets, then fold per vendor.
    vendor_to_buckets: Dict[str, List[str]] = defaultdict(list)
    vendor_meta: Dict[str, Dict] = {}
    for p in projects:
        bucket = derived[p.id][1]
        for vid, vname, vactive in vendors_by_pid.get(p.id, []):
            vendor_to_buckets[vid].append(bucket)
            if vid not in vendor_meta:
                vendor_meta[vid] = {
                    "id": vid, "name": vname, "active": bool(vactive),
                }
    org_cards: List[Dict] = []
    for vid, buckets in vendor_to_buckets.items():
        meta = vendor_meta[vid]
        org_cards.append({
            **meta,
            "projectCount": len(buckets),
            "counts": build_bucket_counts(buckets),
        })
    # Order: project count desc, then name asc.
    org_cards.sort(key=lambda c: (-c["projectCount"], c["name"]))
    org_top = org_cards[:top_orgs] if top_orgs else org_cards

    # ---- Division cards (top-N) ------------------------------------------
    div_to_buckets: Dict[str, List[str]] = defaultdict(list)
    for p in projects:
        code = (p.owner or "").lower() or "unspecified"
        div_to_buckets[code].append(derived[p.id][1])
    div_cards: List[Dict] = []
    for code, buckets in div_to_buckets.items():
        div_cards.append({
            "code": code,
            "label": division_label(code) if code != "unspecified"
                                          else "Unspecified",
            "projectCount": len(buckets),
            "counts": build_bucket_counts(buckets),
        })
    div_cards.sort(key=lambda c: (-c["projectCount"], c["label"]))
    div_top = div_cards[:top_divisions] if top_divisions else div_cards

    return {
        "asOf": today.isoformat(),
        "delayMinDays": delay_min_days,
        "counts": counts,
        "delayedTrack": delayed_top,
        "topOrganisations": org_top,
        "topDivisions": div_top,
    }
