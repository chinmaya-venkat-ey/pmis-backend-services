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
from app.models._cross_schema import Division, Vendor
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


# Static placeholder for the dashboard "pending approvals" count.
# Real wiring (e.g. activity-workflow transitions awaiting review) will
# replace this when the approval module is fully integrated. Until then
# every dashboard counts block surfaces the same static placeholder so
# the FE can bind to the field without conditional logic.
_STATIC_PENDING_APPROVAL_COUNT = 2


def _build_bucket_counts(buckets: List[str]) -> Dict[str, int]:
    """Fold a list of bucket strings into the ``BucketCounts`` shape.

    Always includes ``pendingApprovalCount`` (static placeholder, see
    ``_STATIC_PENDING_APPROVAL_COUNT``) so every dashboard endpoint's
    counts block carries the same key.
    """
    out = {"total": 0, "ontrack": 0, "delayed": 0, "completed": 0}
    for b in buckets:
        out["total"] += 1
        if b in out:
            out[b] += 1
    out["pendingApprovalCount"] = _STATIC_PENDING_APPROVAL_COUNT
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
        self._div_labels: Optional[Dict[str, str]] = None

    def _get_division_labels(self) -> Dict[str, str]:
        """Load active division code→label map from DB (cached per request)."""
        if self._div_labels is None:
            rows = self.db.execute(
                select(Division.code, Division.label).where(Division.active.is_(True))
            ).all()
            self._div_labels = {code.lower(): label for code, label in rows}
        return self._div_labels

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

    def _tally_kind_rows(
        self,
        *,
        out: Dict[str, Dict[str, int]],
        rows: List[Tuple[str, Any, Any]],
        today_ist: _date,
        total_key: str,
        completed_key: str,
        delayed_key: str,
        ontrack_key: str,
    ) -> None:
        """Fold one stream of ``(project_id, status, end_date)`` rows into
        ``out`` using the supplied counter keys. Shared between the
        milestones pass and the activities pass — same bucket dispatch,
        same max-delay tracking, same ``delayedItemCount`` increment."""
        for pid, status, end_dt in rows:
            counters = out.setdefault(pid, _empty_project_counters())
            bucket = _item_bucket(status, end_dt, today_ist)
            counters[total_key] += 1
            if bucket == BUCKET_COMPLETED:
                counters[completed_key] += 1
            elif bucket == BUCKET_DELAYED:
                counters[delayed_key] += 1
                counters["delayedItemCount"] += 1
                d = _item_delay_days(status, end_dt, today_ist)
                if d > counters["maxDelayDays"]:
                    counters["maxDelayDays"] = d
            else:
                counters[ontrack_key] += 1

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

        m_stmt = (
            select(Milestone.project_id, Milestone.status, Milestone.end_date)
            .where(Milestone.project_id.in_(project_ids))
            .where(Milestone.deleted_at.is_(None))
        )
        self._tally_kind_rows(
            out=out,
            rows=self.db.execute(m_stmt).all(),
            today_ist=today_ist,
            total_key="milestonesTotal",
            completed_key="milestonesCompleted",
            delayed_key="milestonesDelayed",
            ontrack_key="milestonesOntrack",
        )

        a_stmt = (
            select(Activity.project_id, Activity.status, Activity.end_date)
            .where(Activity.project_id.in_(project_ids))
            .where(Activity.deleted_at.is_(None))
        )
        self._tally_kind_rows(
            out=out,
            rows=self.db.execute(a_stmt).all(),
            today_ist=today_ist,
            total_key="activitiesTotal",
            completed_key="activitiesCompleted",
            delayed_key="activitiesDelayed",
            ontrack_key="activitiesOntrack",
        )

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
        owner_code = project.owner or ""
        div_labels = self._get_division_labels()
        return {
            "id": project.id,
            "projectCode": project.project_code,
            "name": project.name,
            "description": project.description,
            "organisations": _vendor_chips(vendors),
            "division": owner_code,
            "divisionLabel": div_labels.get(owner_code.lower(), owner_code),
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

    def _build_delayed_track(
        self,
        *,
        projects: List[Project],
        counters: Dict[str, Dict[str, int]],
        vendors_by_pid: Dict[str, List[Tuple[str, str, bool]]],
        delay_min_days: int,
        top_delayed: int,
    ) -> List[Dict[str, Any]]:
        """One row per project whose worst item is delayed >= ``delay_min_days``.
        Sorted desc by ``(delayedItemCount, maxDelayDays)``; truncated to
        ``top_delayed`` (0 = no truncation)."""
        rows: List[Dict[str, Any]] = []
        div_labels = self._get_division_labels()
        for p in projects:
            c = counters[p.id]
            if c["delayedItemCount"] <= 0 or c["maxDelayDays"] < delay_min_days:
                continue
            p_owner = p.owner or ""
            rows.append({
                "id": p.id,
                "projectCode": p.project_code,
                "name": p.name,
                "organisations": _vendor_chips(vendors_by_pid.get(p.id, [])),
                "division": p_owner,
                "divisionLabel": div_labels.get(p_owner.lower(), p_owner),
                "divisionOther": p.owner_other,
                "delayedItemCount": c["delayedItemCount"],
                "maxDelayDays": c["maxDelayDays"],
            })
        rows.sort(
            key=lambda r: (r["delayedItemCount"], r["maxDelayDays"]),
            reverse=True,
        )
        return rows[:top_delayed] if top_delayed else rows

    def _build_organisation_cards(
        self,
        *,
        projects: List[Project],
        derived: Dict[str, Tuple[int, str]],
        vendors_by_pid: Dict[str, List[Tuple[str, str, bool]]],
        top_orgs: int,
    ) -> List[Dict[str, Any]]:
        """Aggregate each vendor's project buckets, sort by
        ``(-projectCount, name)``, truncate to ``top_orgs``."""
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
        cards: List[Dict[str, Any]] = []
        for vid, buckets in vendor_to_buckets.items():
            cards.append({
                **vendor_meta[vid],
                "projectCount": len(buckets),
                "counts": _build_bucket_counts(buckets),
            })
        cards.sort(key=lambda c: (-c["projectCount"], c["name"]))
        return cards[:top_orgs] if top_orgs else cards

    def _build_division_cards(
        self,
        *,
        projects: List[Project],
        derived: Dict[str, Tuple[int, str]],
        top_divisions: int,
    ) -> List[Dict[str, Any]]:
        """Group projects by owner code (lowercased; empty → ``unspecified``);
        sort by ``(-projectCount, label)``, truncate to ``top_divisions``."""
        div_to_buckets: Dict[str, List[str]] = defaultdict(list)
        for p in projects:
            code = (p.owner or "").lower() or "unspecified"
            div_to_buckets[code].append(derived[p.id][1])
        div_labels = self._get_division_labels()
        cards: List[Dict[str, Any]] = []
        for code, buckets in div_to_buckets.items():
            cards.append({
                "code": code,
                "label": (div_labels.get(code, code) if code != "unspecified"
                          else "Unspecified"),
                "projectCount": len(buckets),
                "counts": _build_bucket_counts(buckets),
            })
        cards.sort(key=lambda c: (-c["projectCount"], c["label"]))
        return cards[:top_divisions] if top_divisions else cards

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

        all_buckets = [derived[p.id][1] for p in projects]
        counts = _build_bucket_counts(all_buckets)

        delayed_top = self._build_delayed_track(
            projects=projects,
            counters=counters,
            vendors_by_pid=vendors_by_pid,
            delay_min_days=delay_min_days,
            top_delayed=top_delayed,
        )
        org_top = self._build_organisation_cards(
            projects=projects,
            derived=derived,
            vendors_by_pid=vendors_by_pid,
            top_orgs=top_orgs,
        )
        div_top = self._build_division_cards(
            projects=projects,
            derived=derived,
            top_divisions=top_divisions,
        )

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

    @staticmethod
    def _bucket_filter_passes(bucket: str, bucket_filter: Optional[str]) -> bool:
        """``total``/``None`` always pass; ``active`` = not completed;
        any other value must match the row's bucket exactly."""
        if not bucket_filter or bucket_filter == "total":
            return True
        if bucket_filter == "active":
            return bucket != BUCKET_COMPLETED
        return bucket == bucket_filter

    @staticmethod
    def _q_filter_passes(
        project: Project,
        vendors: List[Tuple[str, str, bool]],
        q: Optional[str],
    ) -> bool:
        """Free-text match over id/projectCode/name/owner/ownerOther + vendor names."""
        if not q:
            return True
        needle = q.lower()
        haystack = [
            project.id,
            project.project_code or "",
            project.name or "",
            project.owner or "",
            project.owner_other or "",
        ]
        haystack.extend([v[1] for v in vendors])
        return any(needle in (p or "").lower() for p in haystack)

    @staticmethod
    def _vendor_filter_passes(
        vendors: List[Tuple[str, str, bool]],
        vendor_id: Optional[str],
    ) -> bool:
        if not vendor_id:
            return True
        return any(v[0] == vendor_id for v in vendors)

    @staticmethod
    def _division_filter_passes(
        project: Project, division: Optional[str],
    ) -> bool:
        if not division:
            return True
        return (project.owner or "").lower() == division.lower()

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
        return (
            self._bucket_filter_passes(bucket, bucket_filter)
            and self._q_filter_passes(project, vendors, q)
            and self._vendor_filter_passes(vendors, vendor_id)
            and self._division_filter_passes(project, division)
        )

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
            "pendingApprovalCount": _STATIC_PENDING_APPROVAL_COUNT,
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
            "pendingApprovalCount": _STATIC_PENDING_APPROVAL_COUNT,
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

    def _assert_project_exists(self, project_id: str) -> None:
        """Raise ``NotFoundError`` if the project is missing or soft-deleted."""
        stmt = (
            select(Project.id)
            .where(Project.id == project_id)
            .where(Project.deleted_at.is_(None))
        )
        if self.db.execute(stmt).scalar_one_or_none() is None:
            raise NotFoundError("The project could not be found.")

    def _sanitize_item_filters(
        self, kind: Optional[str], bucket: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Drop unknown ``kind``/``bucket`` values to ``None`` (acts as
        'no filter'). Matches original silent-fallback behavior."""
        if kind is not None and kind not in self._VALID_ITEM_KINDS:
            kind = None
        if bucket is not None and bucket not in set(ITEM_BUCKETS):
            bucket = None
        return kind, bucket

    @staticmethod
    def _build_milestone_item_row(
        *,
        m: Tuple[Any, ...],
        idx: int,
        activities_by_milestone: Dict[str, List[Tuple[Any, ...]]],
        bucket_value: str,
        delay_value: int,
    ) -> Dict[str, Any]:
        (mid, mname, _pos, mstatus, mstart, mend, mas, mae) = m
        children = activities_by_milestone.get(mid, [])
        child_completed = sum(
            1 for c in children if (c[4] or "") == "completed"
        )
        mp = _progress_pct(child_completed, len(children))
        return {
            "id": mid,
            "kind": "milestone",
            "wbs": f"M{idx}",
            "name": mname,
            "milestoneId": None,
            "milestoneName": None,
            "status": mstatus,
            "bucket": bucket_value,
            "plannedStart": iso_ist(mstart),
            "plannedEnd": iso_ist(mend),
            "actualStart": iso_ist(mas),
            "actualEnd": iso_ist(mae),
            "daysDelayed": delay_value,
            "progressPct": mp,
        }

    def _build_milestone_item_rows(
        self,
        *,
        milestone_rows: List[Tuple[Any, ...]],
        activities_by_milestone: Dict[str, List[Tuple[Any, ...]]],
        milestone_id: Optional[str],
        bucket: Optional[str],
        min_delay: Optional[int],
        today: _date,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx, m in enumerate(milestone_rows, start=1):
            mid, _mname, _pos, mstatus, _mstart, mend, _mas, _mae = m
            if milestone_id is not None and mid != milestone_id:
                continue
            b = _item_bucket(mstatus, mend, today)
            d = _item_delay_days(mstatus, mend, today)
            if bucket is not None and b != bucket:
                continue
            if min_delay is not None and d < min_delay:
                continue
            out.append(self._build_milestone_item_row(
                m=m, idx=idx,
                activities_by_milestone=activities_by_milestone,
                bucket_value=b, delay_value=d,
            ))
        return out

    @staticmethod
    def _build_activity_item_row(
        *,
        a: Tuple[Any, ...],
        wbs: str,
        m_name_by_id: Dict[str, str],
        bucket_value: str,
        delay_value: int,
    ) -> Dict[str, Any]:
        (aid, amid, aname, _apos, astatus, astart, aend, aas, aae) = a
        return {
            "id": aid,
            "kind": "activity",
            "wbs": wbs,
            "name": aname,
            "milestoneId": amid,
            "milestoneName": m_name_by_id.get(amid),
            "status": astatus,
            "bucket": bucket_value,
            "plannedStart": iso_ist(astart),
            "plannedEnd": iso_ist(aend),
            "actualStart": iso_ist(aas),
            "actualEnd": iso_ist(aae),
            "daysDelayed": delay_value,
            "progressPct": 100 if (astatus or "") == "completed" else 0,
        }

    def _build_activity_item_rows(
        self,
        *,
        activity_rows: List[Tuple[Any, ...]],
        m_index_by_id: Dict[str, int],
        m_name_by_id: Dict[str, str],
        bucket: Optional[str],
        min_delay: Optional[int],
        today: _date,
    ) -> List[Dict[str, Any]]:
        """WBS index is consumed for EVERY activity, even ones filtered
        out — matches original behavior. So filtered-out items still
        'use' their A{m}.{n} slot, and the next row sees the next
        sequence number."""
        out: List[Dict[str, Any]] = []
        activity_index_per_milestone: Dict[str, int] = {}
        for a in activity_rows:
            (_aid, amid, _aname, _apos, astatus, _astart, aend, _aas, _aae) = a
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
            out.append(self._build_activity_item_row(
                a=a, wbs=f"A{mi}.{ai}",
                m_name_by_id=m_name_by_id,
                bucket_value=b, delay_value=d,
            ))
        return out

    @staticmethod
    def _tally_item_bucket_counts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts: Dict[str, Any] = {
            "total": len(rows), "ontrack": 0, "delayed": 0, "completed": 0,
        }
        for r in rows:
            b = r["bucket"]
            if b in counts:
                counts[b] += 1
        counts["pendingApprovalCount"] = _STATIC_PENDING_APPROVAL_COUNT
        return counts

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
        self._assert_project_exists(project_id)
        kind, bucket = self._sanitize_item_filters(kind, bucket)
        today = _ist_today()

        milestone_rows = self._fetch_milestone_rows(project_id=project_id)
        m_index_by_id: Dict[str, int] = {}
        m_name_by_id: Dict[str, str] = {}
        for idx, m in enumerate(milestone_rows, start=1):
            m_index_by_id[m[0]] = idx
            m_name_by_id[m[0]] = m[1]

        activity_rows = self._fetch_activity_rows(
            project_id=project_id, milestone_id=milestone_id,
        )
        activities_by_milestone: Dict[str, List[Tuple[Any, ...]]] = {}
        for a in activity_rows:
            activities_by_milestone.setdefault(a[1], []).append(a)

        rows: List[Dict[str, Any]] = []
        if kind in (None, "milestone"):
            rows.extend(self._build_milestone_item_rows(
                milestone_rows=milestone_rows,
                activities_by_milestone=activities_by_milestone,
                milestone_id=milestone_id,
                bucket=bucket,
                min_delay=min_delay,
                today=today,
            ))
        if kind in (None, "activity"):
            rows.extend(self._build_activity_item_rows(
                activity_rows=activity_rows,
                m_index_by_id=m_index_by_id,
                m_name_by_id=m_name_by_id,
                bucket=bucket,
                min_delay=min_delay,
                today=today,
            ))

        return {
            "asOf": today.isoformat(),
            "counts": self._tally_item_bucket_counts(rows),
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
