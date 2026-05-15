"""Dashboard service — consolidated port of the monolith's
``app/api/v3/dashboard/services/{common,summary,projects_list,project_detail,
project_items,organisations}.py`` (6 modules) into a single file.

The monolith split the dashboard surface into 6 sub-modules. The split
was useful when there were 6 separate route files but here the entire
surface lives behind a single router, so we keep one cohesive service
module — easier to read, easier to maintain, no cross-module imports.

Conventions:
  * SQLAlchemy 2.0 ``select(...)`` syntax throughout. (The monolith used
    legacy ``db.query(...)`` chains; ported.)
  * All reads filter ``deleted_at IS NULL`` for projects, milestones,
    activities, and the masters.vendors mirror — soft-deleted rows are
    invisible to the dashboard.
  * Pure derivation functions (item_bucket, project_bucket,
    item_delay_days, progress_pct) are inlined at the top — copies of
    the monolith's ``app/shared/dashboard_derive.py`` helpers, with
    identical semantics so delay counts match byte-for-byte.
  * Wire payloads use camelCase keys (FE compat) — the project-svc Pydantic
    schemas in ``app/schemas/dashboard.py`` mirror this.

Critical: the "delayed" bucket math compares ``end_date`` (planned) to
the IST calendar date of "today" — an item is delayed when it is past
its planned end and not yet ``status == "completed"``. Actual end dates
do NOT factor into the bucket — they only get included in the wire
payload. This matches the monolith exactly.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models._cross_schema import Vendor
from app.models.activity import Activity
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_vendor import ProjectVendor
from app.utilities.timezones import IST, iso_ist


# =========================================================================
# Pure derivation helpers (port of monolith's app/shared/dashboard_derive.py)
# =========================================================================

BUCKET_ONTRACK = "ontrack"
BUCKET_DELAYED = "delayed"
BUCKET_COMPLETED = "completed"

# Order matters for pie / KPI display. Both project and item buckets share
# this triple.
PROJECT_BUCKETS: Tuple[str, ...] = (BUCKET_ONTRACK, BUCKET_DELAYED, BUCKET_COMPLETED)
ITEM_BUCKETS: Tuple[str, ...] = (BUCKET_ONTRACK, BUCKET_DELAYED, BUCKET_COMPLETED)

# Project lifecycle -> ``completed`` mapping. Anything else needs the
# item walk below.
_LIFECYCLE_COMPLETED = frozenset({"closed"})

# Status the M/A row carries when work is done.
_ITEM_STATUS_COMPLETED = "completed"

# Division code → display label. Backend stores codes (tmd1/tmd2/others);
# the dashboard renders the human label.
_DIVISION_LABELS = {
    "tmd1": "TMD-I",
    "tmd2": "TMD-II",
    "others": "Others",
}


def _ist_today() -> _date:
    """Today's calendar date in IST. Single helper so every dashboard
    endpoint uses the same instant on a given request."""
    return datetime.now(timezone.utc).astimezone(IST).date()


def _ist_calendar_date(dt: Optional[datetime]) -> Optional[_date]:
    """Project ``dt`` onto the IST calendar. Naive inputs are assumed
    UTC (matches the DateTime(timezone=True) storage contract)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).date()


def _item_bucket(
    status: Optional[str],
    expected_end: Optional[datetime],
    today_ist_date: _date,
) -> str:
    """Bucket a single milestone or activity.

    Rules (mutually exclusive):
      1. ``status == "completed"`` → ``completed`` (wins even when the
         row finished after its planned end).
      2. else if expected end is strictly before today (IST)
         → ``delayed``.
      3. else → ``ontrack``.

    A row with no expected end (legacy, pre-required-dates) is treated
    as ``ontrack`` — it has no deadline to breach.
    """
    if (status or "") == _ITEM_STATUS_COMPLETED:
        return BUCKET_COMPLETED
    end_d = _ist_calendar_date(expected_end)
    if end_d is not None and end_d < today_ist_date:
        return BUCKET_DELAYED
    return BUCKET_ONTRACK


def _item_delay_days(
    status: Optional[str],
    expected_end: Optional[datetime],
    today_ist_date: _date,
) -> int:
    """Days delayed for a milestone or activity.

    Returns 0 unless the row is in the ``delayed`` bucket (not completed
    AND expected end < today IST). Then returns the integer count of
    calendar days past the deadline.
    """
    if (status or "") == _ITEM_STATUS_COMPLETED:
        return 0
    end_d = _ist_calendar_date(expected_end)
    if end_d is None or end_d >= today_ist_date:
        return 0
    return (today_ist_date - end_d).days


def _project_bucket(
    lifecycle_status: Optional[str],
    item_buckets_seen: List[str],
) -> str:
    """Bucket a project from its lifecycle + the buckets of its items.

    Rules (mutually exclusive — three buckets):
      * lifecycle ``closed``                            → ``completed``
      * any item bucket == ``delayed``                  → ``delayed``
      * otherwise (or empty project)                    → ``ontrack``
    """
    s = (lifecycle_status or "").lower()
    if s in _LIFECYCLE_COMPLETED:
        return BUCKET_COMPLETED
    for b in item_buckets_seen:
        if b == BUCKET_DELAYED:
            return BUCKET_DELAYED
    return BUCKET_ONTRACK


def _progress_pct(completed_ma: int, total_ma: int) -> int:
    """Project-level progress as a rounded integer percentage.

    Defined as ``(completed M + completed A) / (total M + total A)``
    over live rows. ``0`` when there are no items.
    """
    if total_ma <= 0:
        return 0
    return int(round(completed_ma * 100.0 / total_ma))


def _division_label(code: str) -> str:
    """Human label for a division code. Falls back to the code itself
    if the catalog grows beyond the known three."""
    if not code:
        return "—"
    return _DIVISION_LABELS.get(code.lower(), code)


# =========================================================================
# Per-project counter helpers
# =========================================================================

def _empty_project_counters() -> Dict[str, int]:
    return {
        "milestonesTotal": 0,
        "milestonesCompleted": 0,
        "milestonesDelayed": 0,
        "milestonesOntrack": 0,
        "activitiesTotal": 0,
        "activitiesCompleted": 0,
        "activitiesDelayed": 0,
        "activitiesOntrack": 0,
        # Items past their planned end and not completed.
        "delayedItemCount": 0,
        # Largest single delay across this project's items.
        "maxDelayDays": 0,
    }


def _build_bucket_counts(buckets: List[str]) -> Dict[str, int]:
    """Fold a list of bucket strings into the ``BucketCounts`` shape."""
    out = {"total": 0, "ontrack": 0, "delayed": 0, "completed": 0}
    for b in buckets:
        out["total"] += 1
        if b in out:
            out[b] += 1
    return out


def _vendor_chip(vendor_id: str, vendor_name: str, active: bool) -> Dict[str, Any]:
    return {"id": vendor_id, "name": vendor_name, "active": bool(active)}


def _vendor_chips(rows: List[Tuple[str, str, bool]]) -> List[Dict[str, Any]]:
    return [_vendor_chip(*r) for r in rows]


# =========================================================================
# DashboardService — single class fronting the 6 endpoints
# =========================================================================

class DashboardService:
    """Pure read paths backing the 6 dashboard endpoints. No writes
    anywhere — the constructor only holds the session."""

    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------------
    # Low-level repo-style helpers (kept inline; the monolith's
    # DashboardRepository was a thin facade and breaking it out again
    # would add noise without value).
    # ---------------------------------------------------------------------

    def _list_live_projects(
        self, *, ids: Optional[List[str]] = None,
    ) -> List[Project]:
        """All non-deleted projects ordered by ``name`` ASC. ``ids``
        narrows to that set (empty list → no rows)."""
        stmt = select(Project).where(Project.deleted_at.is_(None))
        if ids is not None:
            if not ids:
                return []
            stmt = stmt.where(Project.id.in_(ids))
        stmt = stmt.order_by(Project.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def _fetch_per_project_counters(
        self, *, project_ids: List[str], today_ist: _date,
    ) -> Dict[str, Dict[str, int]]:
        """For each project return its M/A counter dict, folded by
        bucket. Two SQL passes total (one milestones, one activities).
        Missing projects come back with a zeroed counter dict."""
        out: Dict[str, Dict[str, int]] = {
            pid: _empty_project_counters() for pid in project_ids
        }
        if not project_ids:
            return out

        # --- milestones --------------------------------------------------
        m_stmt = (
            select(Milestone.project_id, Milestone.status, Milestone.end_date)
            .where(Milestone.project_id.in_(project_ids))
            .where(Milestone.deleted_at.is_(None))
        )
        for pid, status, end_dt in self.db.execute(m_stmt).all():
            counters = out.setdefault(pid, _empty_project_counters())
            bucket = _item_bucket(status, end_dt, today_ist)
            counters["milestonesTotal"] += 1
            if bucket == BUCKET_COMPLETED:
                counters["milestonesCompleted"] += 1
            elif bucket == BUCKET_DELAYED:
                counters["milestonesDelayed"] += 1
                counters["delayedItemCount"] += 1
                d = _item_delay_days(status, end_dt, today_ist)
                if d > counters["maxDelayDays"]:
                    counters["maxDelayDays"] = d
            else:
                counters["milestonesOntrack"] += 1

        # --- activities --------------------------------------------------
        a_stmt = (
            select(Activity.project_id, Activity.status, Activity.end_date)
            .where(Activity.project_id.in_(project_ids))
            .where(Activity.deleted_at.is_(None))
        )
        for pid, status, end_dt in self.db.execute(a_stmt).all():
            counters = out.setdefault(pid, _empty_project_counters())
            bucket = _item_bucket(status, end_dt, today_ist)
            counters["activitiesTotal"] += 1
            if bucket == BUCKET_COMPLETED:
                counters["activitiesCompleted"] += 1
            elif bucket == BUCKET_DELAYED:
                counters["activitiesDelayed"] += 1
                counters["delayedItemCount"] += 1
                d = _item_delay_days(status, end_dt, today_ist)
                if d > counters["maxDelayDays"]:
                    counters["maxDelayDays"] = d
            else:
                counters["activitiesOntrack"] += 1

        return out

    @staticmethod
    def _derive_progress_and_bucket(
        *, counters: Dict[str, int], lifecycle_status: str,
    ) -> Tuple[int, str]:
        """Combine the counter dict + lifecycle into ``(progressPct,
        bucket)``."""
        total_ma = counters["milestonesTotal"] + counters["activitiesTotal"]
        completed_ma = (
            counters["milestonesCompleted"] + counters["activitiesCompleted"]
        )
        seen_buckets: List[str] = []
        if counters["milestonesDelayed"] or counters["activitiesDelayed"]:
            seen_buckets.append(BUCKET_DELAYED)
        return (
            _progress_pct(completed_ma, total_ma),
            _project_bucket(lifecycle_status, seen_buckets),
        )

    def _fetch_milestone_rows(
        self, *, project_id: str,
    ) -> List[Tuple[Any, ...]]:
        """Live milestones for a project, ordered by position. Returns
        tuples ``(id, name, position, status, start_date, end_date,
        actual_start_date, actual_end_date)``."""
        stmt = (
            select(
                Milestone.id,
                Milestone.name,
                Milestone.position,
                Milestone.status,
                Milestone.start_date,
                Milestone.end_date,
                Milestone.actual_start_date,
                Milestone.actual_end_date,
            )
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .order_by(Milestone.position.asc())
        )
        return [tuple(r) for r in self.db.execute(stmt).all()]

    def _fetch_activity_rows(
        self, *, project_id: str, milestone_id: Optional[str] = None,
    ) -> List[Tuple[Any, ...]]:
        """Live activities for a project (optionally narrowed to one
        milestone). Returns tuples ``(id, milestone_id, name, position,
        status, start_date, end_date, actual_start_date,
        actual_end_date)``."""
        stmt = (
            select(
                Activity.id,
                Activity.milestone_id,
                Activity.name,
                Activity.position,
                Activity.status,
                Activity.start_date,
                Activity.end_date,
                Activity.actual_start_date,
                Activity.actual_end_date,
            )
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        )
        if milestone_id is not None:
            stmt = stmt.where(Activity.milestone_id == milestone_id)
        stmt = stmt.order_by(
            Activity.milestone_id.asc(), Activity.position.asc(),
        )
        return [tuple(r) for r in self.db.execute(stmt).all()]

    def _list_live_vendors(self) -> List[Vendor]:
        """All non-deleted vendors (active + inactive), ordered by name ASC."""
        stmt = (
            select(Vendor)
            .where(Vendor.deleted_at.is_(None))
            .order_by(Vendor.name.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def _get_vendor(self, vendor_id: str) -> Optional[Vendor]:
        stmt = (
            select(Vendor)
            .where(Vendor.id == vendor_id)
            .where(Vendor.deleted_at.is_(None))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _fetch_vendors_for_projects(
        self, *, project_ids: List[str],
    ) -> Dict[str, List[Tuple[str, str, bool]]]:
        """For each project return its attached live vendors as tuples
        ``(vendor_id, vendor_name, vendor_active)``. Vendors deleted at
        the catalog level are filtered out."""
        out: Dict[str, List[Tuple[str, str, bool]]] = defaultdict(list)
        if not project_ids:
            return out
        stmt = (
            select(
                ProjectVendor.project_id,
                Vendor.id,
                Vendor.name,
                Vendor.active,
            )
            .join(Vendor, Vendor.id == ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id.in_(project_ids))
            .where(Vendor.deleted_at.is_(None))
            .order_by(Vendor.name.asc())
        )
        for pid, vid, vname, vactive in self.db.execute(stmt).all():
            out[pid].append((vid, vname, bool(vactive)))
        return out

    def _fetch_project_ids_for_vendor(self, vendor_id: str) -> List[str]:
        """All project ids attached to ``vendor_id`` whose project rows
        are live."""
        stmt = (
            select(ProjectVendor.project_id)
            .join(
                Project,
                and_(
                    Project.id == ProjectVendor.project_id,
                    Project.deleted_at.is_(None),
                ),
            )
            .where(ProjectVendor.vendor_id == vendor_id)
        )
        return [r[0] for r in self.db.execute(stmt).all()]

    # ---------------------------------------------------------------------
    # Card composition
    # ---------------------------------------------------------------------

    def _build_project_card(
        self,
        *,
        project: Project,
        counters: Dict[str, int],
        vendors: List[Tuple[str, str, bool]],
        progress_pct: int,
        bucket: str,
    ) -> Dict[str, Any]:
        """Compose the dict that matches the ``ProjectCard`` schema."""
        return {
            "id": project.id,
            "projectCode": project.project_code,
            "name": project.name,
            "description": project.description,
            "organisations": _vendor_chips(vendors),
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

    def _fetch_projects_with_buckets(
        self, *, today_ist: _date, project_ids: Optional[List[str]] = None,
    ) -> Tuple[
        List[Project],
        Dict[str, Dict[str, int]],
        Dict[str, List[Tuple[str, str, bool]]],
        Dict[str, Tuple[int, str]],
    ]:
        """One-stop fetch + derive used by summary, project list, and
        organisations pages. Returns ``(projects, counters_by_pid,
        vendors_by_pid, derived_by_pid)`` where
        ``derived_by_pid[pid] == (progressPct, bucket)``."""
        if project_ids is None:
            projects = self._list_live_projects()
        else:
            projects = self._list_live_projects(ids=project_ids)
        pids = [p.id for p in projects]
        counters = self._fetch_per_project_counters(
            project_ids=pids, today_ist=today_ist,
        )
        vendors_by_pid = self._fetch_vendors_for_projects(project_ids=pids)
        derived: Dict[str, Tuple[int, str]] = {}
        for p in projects:
            derived[p.id] = self._derive_progress_and_bucket(
                counters=counters[p.id], lifecycle_status=p.status,
            )
        return projects, counters, vendors_by_pid, derived

    # =====================================================================
    # Endpoint #1 — GET /project/dashboard/summary
    # =====================================================================

    def get_summary(
        self,
        *,
        delay_min_days: int = 5,
        top_delayed: int = 4,
        top_orgs: int = 3,
        top_divisions: int = 3,
    ) -> Dict[str, Any]:
        """Summary view payload — KPIs + pie + delayed track + top
        org/division cards."""
        today = _ist_today()

        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today)
        )

        # ---- KPI strip / pie counts -------------------------------------
        all_buckets = [derived[p.id][1] for p in projects]
        counts = _build_bucket_counts(all_buckets)

        # ---- Delayed track (one row per project) ------------------------
        delayed_rows: List[Dict[str, Any]] = []
        for p in projects:
            c = counters[p.id]
            # Only include projects whose worst item is delayed >= floor.
            # Counts every delayed item in that project, not just worst.
            if c["delayedItemCount"] <= 0 or c["maxDelayDays"] < delay_min_days:
                continue
            delayed_rows.append({
                "id": p.id,
                "projectCode": p.project_code,
                "name": p.name,
                "organisations": _vendor_chips(vendors_by_pid.get(p.id, [])),
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

        # ---- Organisation cards (top-N by project count) ----------------
        vendor_to_buckets: Dict[str, List[str]] = defaultdict(list)
        vendor_meta: Dict[str, Dict[str, Any]] = {}
        for p in projects:
            bucket = derived[p.id][1]
            for vid, vname, vactive in vendors_by_pid.get(p.id, []):
                vendor_to_buckets[vid].append(bucket)
                if vid not in vendor_meta:
                    vendor_meta[vid] = {
                        "id": vid, "name": vname, "active": bool(vactive),
                    }
        org_cards: List[Dict[str, Any]] = []
        for vid, buckets in vendor_to_buckets.items():
            meta = vendor_meta[vid]
            org_cards.append({
                **meta,
                "projectCount": len(buckets),
                "counts": _build_bucket_counts(buckets),
            })
        org_cards.sort(key=lambda c: (-c["projectCount"], c["name"]))
        org_top = org_cards[:top_orgs] if top_orgs else org_cards

        # ---- Division cards (top-N) -------------------------------------
        div_to_buckets: Dict[str, List[str]] = defaultdict(list)
        for p in projects:
            code = (p.owner or "").lower() or "unspecified"
            div_to_buckets[code].append(derived[p.id][1])
        div_cards: List[Dict[str, Any]] = []
        for code, buckets in div_to_buckets.items():
            div_cards.append({
                "code": code,
                "label": _division_label(code) if code != "unspecified"
                                              else "Unspecified",
                "projectCount": len(buckets),
                "counts": _build_bucket_counts(buckets),
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

    # =====================================================================
    # Endpoint #2 — GET /project/dashboard/projects
    # =====================================================================

    _VALID_BUCKETS_FOR_LIST = set(PROJECT_BUCKETS) | {"total", "active"}

    def _matches_project_filters(
        self,
        *,
        project: Project,
        vendors: List[Tuple[str, str, bool]],
        bucket: str,
        bucket_filter: Optional[str],
        q: Optional[str],
        vendor_id: Optional[str],
        division: Optional[str],
    ) -> bool:
        # Bucket: ``total`` and ``None`` both pass; ``active`` means
        # not-completed; otherwise an exact bucket match.
        if bucket_filter and bucket_filter != "total":
            if bucket_filter == "active":
                if bucket == BUCKET_COMPLETED:
                    return False
            elif bucket != bucket_filter:
                return False

        # Free-text search across id/projectCode/name/division/vendor names.
        if q:
            needle = q.lower()
            haystack = [
                project.id,
                project.project_code or "",
                project.name or "",
                project.owner or "",
                project.owner_other or "",
            ]
            haystack.extend([v[1] for v in vendors])
            if not any(needle in (p or "").lower() for p in haystack):
                return False

        if vendor_id:
            if not any(v[0] == vendor_id for v in vendors):
                return False

        if division:
            target = division.lower()
            if (project.owner or "").lower() != target:
                return False

        return True

    def list_projects(
        self,
        *,
        bucket: Optional[str] = None,
        q: Optional[str] = None,
        vendor_id: Optional[str] = None,
        division: Optional[str] = None,
        page: int = 1,
        page_size: int = 200,
    ) -> Dict[str, Any]:
        """Paginated project cards with optional filters."""
        if bucket is not None and bucket not in self._VALID_BUCKETS_FOR_LIST:
            # Treat unknown filter as "no filter" — matches the monolith.
            bucket = None

        if page < 1:
            page = 1
        page_size = max(1, min(page_size, 500))

        today = _ist_today()
        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today)
        )

        # Filter step.
        matched: List[Project] = []
        for p in projects:
            _prog, b = derived[p.id]
            if self._matches_project_filters(
                project=p,
                vendors=vendors_by_pid.get(p.id, []),
                bucket=b,
                bucket_filter=bucket,
                q=q,
                vendor_id=vendor_id,
                division=division,
            ):
                matched.append(p)

        # Counts over the FILTERED set so the FE renders the small pie
        # next to the listing.
        counts = _build_bucket_counts([derived[p.id][1] for p in matched])

        # Pagination.
        total = len(matched)
        start = (page - 1) * page_size
        end = start + page_size
        page_projects = matched[start:end]

        cards = [
            self._build_project_card(
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

    # =====================================================================
    # Endpoint #3 — GET /project/dashboard/projects/{id}
    # =====================================================================

    # Pending approvals KPI is intentionally static at zero — approval
    # workflow is deferred to the next phase.
    _STATIC_PENDING_APPROVALS = 0

    def get_project_detail(
        self,
        *,
        project_id: str,
        delay_min_days: int = 5,
    ) -> Dict[str, Any]:
        """Project View payload — header + KPIs + pie + delayed track."""
        today = _ist_today()

        projects = self._list_live_projects(ids=[project_id])
        if not projects:
            raise NotFoundError("The project could not be found.")
        project = projects[0]

        counters_all = self._fetch_per_project_counters(
            project_ids=[project_id], today_ist=today,
        )
        counters = counters_all[project_id]
        vendors = self._fetch_vendors_for_projects(
            project_ids=[project_id],
        ).get(project_id, [])
        progress_pct, bucket = self._derive_progress_and_bucket(
            counters=counters, lifecycle_status=project.status,
        )

        # ---- Card -------------------------------------------------------
        card = self._build_project_card(
            project=project,
            counters=counters,
            vendors=vendors,
            progress_pct=progress_pct,
            bucket=bucket,
        )

        # ---- Five KPI tiles --------------------------------------------
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
            "pendingApprovals": self._STATIC_PENDING_APPROVALS,
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

        # ---- Delayed track rows ----------------------------------------
        delayed_rows: List[Dict[str, Any]] = []

        # Pre-fetch milestones for WBS labels + names (used by activity
        # rows for the contextual "milestone" cell).
        milestone_rows = self._fetch_milestone_rows(project_id=project_id)
        m_index_by_id: Dict[str, int] = {}
        m_name_by_id: Dict[str, str] = {}
        for idx, m in enumerate(milestone_rows, start=1):
            mid = m[0]
            m_index_by_id[mid] = idx
            m_name_by_id[mid] = m[1]

        for idx, m in enumerate(milestone_rows, start=1):
            (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
            b = _item_bucket(mstatus, mend, today)
            if b != BUCKET_DELAYED:
                continue
            d = _item_delay_days(mstatus, mend, today)
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
        activity_rows = self._fetch_activity_rows(project_id=project_id)
        activity_index_per_milestone: Dict[str, int] = {}
        for a in activity_rows:
            (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
            activity_index_per_milestone[amid] = (
                activity_index_per_milestone.get(amid, 0) + 1
            )
            ai = activity_index_per_milestone[amid]
            mi = m_index_by_id.get(amid, 0)
            b = _item_bucket(astatus, aend, today)
            if b != BUCKET_DELAYED:
                continue
            d = _item_delay_days(astatus, aend, today)
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

    # =====================================================================
    # Endpoint #4 — GET /project/dashboard/projects/{id}/items
    # =====================================================================

    _VALID_ITEM_KINDS = {"milestone", "activity"}

    def get_project_items(
        self,
        *,
        project_id: str,
        kind: Optional[str] = None,
        bucket: Optional[str] = None,
        milestone_id: Optional[str] = None,
        min_delay: Optional[int] = None,
    ) -> Dict[str, Any]:
        """M/A drill-down rows under a project (with filters)."""
        # Project existence check — single live row lookup.
        exists_stmt = (
            select(Project.id)
            .where(Project.id == project_id)
            .where(Project.deleted_at.is_(None))
        )
        if self.db.execute(exists_stmt).scalar_one_or_none() is None:
            raise NotFoundError("The project could not be found.")

        if kind is not None and kind not in self._VALID_ITEM_KINDS:
            kind = None
        if bucket is not None and bucket not in set(ITEM_BUCKETS):
            bucket = None

        today = _ist_today()

        rows: List[Dict[str, Any]] = []

        # Pre-fetch milestones once — for both milestone rows + WBS index.
        milestone_rows = self._fetch_milestone_rows(project_id=project_id)
        m_index_by_id: Dict[str, int] = {}
        m_name_by_id: Dict[str, str] = {}
        for idx, m in enumerate(milestone_rows, start=1):
            m_index_by_id[m[0]] = idx
            m_name_by_id[m[0]] = m[1]

        # Activities are needed for milestone progress rollups even if
        # the caller asked for milestones only.
        activity_rows = self._fetch_activity_rows(
            project_id=project_id, milestone_id=milestone_id,
        )
        activities_by_milestone: Dict[str, List[Tuple[Any, ...]]] = {}
        activity_index_per_milestone: Dict[str, int] = {}
        for a in activity_rows:
            amid = a[1]
            activities_by_milestone.setdefault(amid, []).append(a)

        # ---- Milestones -------------------------------------------------
        if kind in (None, "milestone"):
            for idx, m in enumerate(milestone_rows, start=1):
                (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
                if milestone_id is not None and mid != milestone_id:
                    continue
                b = _item_bucket(mstatus, mend, today)
                d = _item_delay_days(mstatus, mend, today)
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
                mp = _progress_pct(child_completed, len(children))
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

        # ---- Activities -------------------------------------------------
        if kind in (None, "activity"):
            for a in activity_rows:
                (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
                activity_index_per_milestone[amid] = (
                    activity_index_per_milestone.get(amid, 0) + 1
                )
                ai = activity_index_per_milestone[amid]
                mi = m_index_by_id.get(amid, 0)
                b = _item_bucket(astatus, aend, today)
                d = _item_delay_days(astatus, aend, today)
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

    # =====================================================================
    # Endpoint #5 — GET /project/dashboard/organisations
    # =====================================================================

    def list_organisations(self) -> Dict[str, Any]:
        """Vendor grid + active/inactive pie."""
        today = _ist_today()

        vendors = self._list_live_vendors()

        projects, _counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(today_ist=today)
        )

        vendor_to_buckets: Dict[str, List[str]] = defaultdict(list)
        for p in projects:
            b = derived[p.id][1]
            for vid, _vname, _vactive in vendors_by_pid.get(p.id, []):
                vendor_to_buckets[vid].append(b)

        org_cards: List[Dict[str, Any]] = []
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
                "counts": _build_bucket_counts(buckets),
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

    # =====================================================================
    # Endpoint #6 — GET /project/dashboard/organisations/{vendor_id}
    # =====================================================================

    def get_organisation_detail(self, *, vendor_id: str) -> Dict[str, Any]:
        """Vendor detail — KPI counts + project pie + project list."""
        today = _ist_today()

        vendor = self._get_vendor(vendor_id)
        if vendor is None:
            raise NotFoundError("The organisation could not be found.")

        project_ids = self._fetch_project_ids_for_vendor(vendor_id)
        projects, counters, vendors_by_pid, derived = (
            self._fetch_projects_with_buckets(
                today_ist=today, project_ids=project_ids,
            )
        )

        cards = [
            self._build_project_card(
                project=p,
                counters=counters[p.id],
                vendors=vendors_by_pid.get(p.id, []),
                progress_pct=derived[p.id][0],
                bucket=derived[p.id][1],
            )
            for p in projects
        ]

        bucket_list = [derived[p.id][1] for p in projects]
        pie = _build_bucket_counts(bucket_list)

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
