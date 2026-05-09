"""Read-only repository feeding the ``/api/v3/dashboard/*`` surface.

Design constraints:

  * Pure read paths. No writes anywhere — dashboard never mutates state.
  * Cheap aggregation. The Summary view counts buckets across hundreds
    or thousands of projects; we cannot afford an N+1 walk per project.
    Each method is one SQL pass per kind (milestones, activities,
    project_vendors).
  * Soft-delete-aware. Every M / A / Project / project_vendor query
    filters ``deleted_at IS NULL`` (and ``active=True`` for the
    project-level ``active`` flag where applicable).

Bucketing logic lives in ``app/shared/dashboard_derive.py`` —
this module only fetches rows + folds them into per-project counters.
"""
from collections import defaultdict
from datetime import date as _date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models.activity import ActivityModel
from ..models.milestone import MilestoneModel
from ..models.project import ProjectModel
from ..models.project_vendor import ProjectVendorModel
from ..models.vendor import VendorModel
from ....shared.dashboard_derive import (
    BUCKET_COMPLETED,
    BUCKET_DELAYED,
    BUCKET_ONTRACK,
    PROJECT_BUCKETS,
    empty_bucket_counts,
    item_bucket,
    item_delay_days,
    project_bucket,
    progress_pct,
)


# ---------------------------------------------------------------------------
# Per-project counter shape used everywhere
# ---------------------------------------------------------------------------

def _empty_project_counters() -> Dict:
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


class DashboardRepository:
    """Lightweight read-only access for the dashboard surface."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------------------
    # Live projects
    # ---------------------------------------------------------------------

    def list_live_projects(
        self,
        *,
        ids: Optional[List[str]] = None,
    ) -> List[ProjectModel]:
        """All non-deleted projects (no pagination — caller folds into
        the right shape). Ordered by ``name`` ASC.

        If ``ids`` is given, restrict to that set (used by the vendor
        detail page where we already filtered by vendor).
        """
        q = (
            self.db.query(ProjectModel)
            .filter(ProjectModel.deleted_at.is_(None))
        )
        if ids is not None:
            if not ids:
                return []
            q = q.filter(ProjectModel.id.in_(ids))
        return q.order_by(ProjectModel.name.asc()).all()

    # ---------------------------------------------------------------------
    # Per-project M/A counters (single SQL pass per kind)
    # ---------------------------------------------------------------------

    def fetch_per_project_counters(
        self,
        *,
        project_ids: List[str],
        today_ist: _date,
    ) -> Dict[str, Dict]:
        """For each project in ``project_ids`` return a dict of M/A
        counters folded by bucket. Missing projects (no live M/A) come
        back with a zeroed counter dict.

        Two SQL passes total: one over live milestones, one over live
        activities. Both filter ``project_id IN :ids`` and
        ``deleted_at IS NULL``.
        """
        out: Dict[str, Dict] = {pid: _empty_project_counters() for pid in project_ids}
        if not project_ids:
            return out

        # --- milestones -------------------------------------------------
        m_rows = (
            self.db.query(
                MilestoneModel.project_id,
                MilestoneModel.status,
                MilestoneModel.end_date,
            )
            .filter(MilestoneModel.project_id.in_(project_ids))
            .filter(MilestoneModel.deleted_at.is_(None))
            .all()
        )
        for pid, status, end_dt in m_rows:
            counters = out.setdefault(pid, _empty_project_counters())
            bucket = item_bucket(status, end_dt, today_ist)
            counters["milestonesTotal"] += 1
            if bucket == BUCKET_COMPLETED:
                counters["milestonesCompleted"] += 1
            elif bucket == BUCKET_DELAYED:
                counters["milestonesDelayed"] += 1
                counters["delayedItemCount"] += 1
                d = item_delay_days(status, end_dt, today_ist)
                if d > counters["maxDelayDays"]:
                    counters["maxDelayDays"] = d
            else:
                counters["milestonesOntrack"] += 1

        # --- activities -------------------------------------------------
        a_rows = (
            self.db.query(
                ActivityModel.project_id,
                ActivityModel.status,
                ActivityModel.end_date,
            )
            .filter(ActivityModel.project_id.in_(project_ids))
            .filter(ActivityModel.deleted_at.is_(None))
            .all()
        )
        for pid, status, end_dt in a_rows:
            counters = out.setdefault(pid, _empty_project_counters())
            bucket = item_bucket(status, end_dt, today_ist)
            counters["activitiesTotal"] += 1
            if bucket == BUCKET_COMPLETED:
                counters["activitiesCompleted"] += 1
            elif bucket == BUCKET_DELAYED:
                counters["activitiesDelayed"] += 1
                counters["delayedItemCount"] += 1
                d = item_delay_days(status, end_dt, today_ist)
                if d > counters["maxDelayDays"]:
                    counters["maxDelayDays"] = d
            else:
                counters["activitiesOntrack"] += 1

        return out

    @staticmethod
    def derive_progress_and_bucket(
        *,
        counters: Dict,
        lifecycle_status: str,
    ) -> Tuple[int, str]:
        """Combine the counter dict + lifecycle into ``(progressPct,
        bucket)``. Pure function — broken out so it's testable on its
        own."""
        total_ma = counters["milestonesTotal"] + counters["activitiesTotal"]
        completed_ma = (
            counters["milestonesCompleted"] + counters["activitiesCompleted"]
        )
        item_buckets: List[str] = []
        # The delayed-flag signal is sufficient — we only care that
        # *some* item is delayed for the published-bucket rule.
        if counters["milestonesDelayed"] or counters["activitiesDelayed"]:
            item_buckets.append(BUCKET_DELAYED)
        return (
            progress_pct(completed_ma, total_ma),
            project_bucket(lifecycle_status, item_buckets),
        )

    # ---------------------------------------------------------------------
    # M/A item rows for drill-down tables
    # ---------------------------------------------------------------------

    def fetch_milestone_rows(
        self,
        *,
        project_id: str,
    ) -> List[Tuple]:
        """Live milestones for a project, ordered by position. Returns
        tuples ``(id, name, position, status, start_date, end_date,
        actual_start_date, actual_end_date)``."""
        return (
            self.db.query(
                MilestoneModel.id,
                MilestoneModel.name,
                MilestoneModel.position,
                MilestoneModel.status,
                MilestoneModel.start_date,
                MilestoneModel.end_date,
                MilestoneModel.actual_start_date,
                MilestoneModel.actual_end_date,
            )
            .filter(MilestoneModel.project_id == project_id)
            .filter(MilestoneModel.deleted_at.is_(None))
            .order_by(MilestoneModel.position.asc())
            .all()
        )

    def fetch_activity_rows(
        self,
        *,
        project_id: str,
        milestone_id: Optional[str] = None,
    ) -> List[Tuple]:
        """Live activities for a project (optionally narrowed to one
        milestone). Returns tuples ``(id, milestone_id, name, position,
        status, start_date, end_date, actual_start_date,
        actual_end_date)``."""
        q = (
            self.db.query(
                ActivityModel.id,
                ActivityModel.milestone_id,
                ActivityModel.name,
                ActivityModel.position,
                ActivityModel.status,
                ActivityModel.start_date,
                ActivityModel.end_date,
                ActivityModel.actual_start_date,
                ActivityModel.actual_end_date,
            )
            .filter(ActivityModel.project_id == project_id)
            .filter(ActivityModel.deleted_at.is_(None))
        )
        if milestone_id is not None:
            q = q.filter(ActivityModel.milestone_id == milestone_id)
        return q.order_by(
            ActivityModel.milestone_id.asc(),
            ActivityModel.position.asc(),
        ).all()

    # ---------------------------------------------------------------------
    # Vendors
    # ---------------------------------------------------------------------

    def list_live_vendors(self) -> List[VendorModel]:
        """All non-deleted vendors (active + inactive). Ordered by name
        ASC. Used by the Organization view's signal cards."""
        return (
            self.db.query(VendorModel)
            .filter(VendorModel.deleted_at.is_(None))
            .order_by(VendorModel.name.asc())
            .all()
        )

    def get_vendor(self, vendor_id: str) -> Optional[VendorModel]:
        return (
            self.db.query(VendorModel)
            .filter(VendorModel.id == vendor_id)
            .filter(VendorModel.deleted_at.is_(None))
            .first()
        )

    def fetch_vendors_for_projects(
        self,
        *,
        project_ids: List[str],
    ) -> Dict[str, List[Tuple[str, str, bool]]]:
        """For each project return its attached live vendors as tuples
        ``(vendor_id, vendor_name, vendor_active)``. Vendors deleted at
        the catalog level (vendors.deleted_at != NULL) are filtered
        out — the project_vendors mapping row is preserved historically
        but the dashboard only shows live vendors.
        """
        out: Dict[str, List[Tuple[str, str, bool]]] = defaultdict(list)
        if not project_ids:
            return out
        rows = (
            self.db.query(
                ProjectVendorModel.project_id,
                VendorModel.id,
                VendorModel.name,
                VendorModel.active,
            )
            .join(VendorModel, VendorModel.id == ProjectVendorModel.vendor_id)
            .filter(ProjectVendorModel.project_id.in_(project_ids))
            .filter(VendorModel.deleted_at.is_(None))
            .order_by(VendorModel.name.asc())
            .all()
        )
        for pid, vid, vname, vactive in rows:
            out[pid].append((vid, vname, bool(vactive)))
        return out

    def fetch_project_ids_for_vendor(self, vendor_id: str) -> List[str]:
        """All project ids attached to ``vendor_id`` whose project
        rows are live (not soft-deleted)."""
        rows = (
            self.db.query(ProjectVendorModel.project_id)
            .join(
                ProjectModel,
                and_(
                    ProjectModel.id == ProjectVendorModel.project_id,
                    ProjectModel.deleted_at.is_(None),
                ),
            )
            .filter(ProjectVendorModel.vendor_id == vendor_id)
            .all()
        )
        return [r[0] for r in rows]

    def fetch_vendor_project_counts(self) -> Dict[str, int]:
        """``{vendor_id: count_of_live_projects}``. One SQL pass —
        excludes vendor mappings whose project row is soft-deleted."""
        rows = (
            self.db.query(
                ProjectVendorModel.vendor_id,
                func.count(ProjectVendorModel.project_id),
            )
            .join(
                ProjectModel,
                and_(
                    ProjectModel.id == ProjectVendorModel.project_id,
                    ProjectModel.deleted_at.is_(None),
                ),
            )
            .group_by(ProjectVendorModel.vendor_id)
            .all()
        )
        return {vid: int(cnt) for vid, cnt in rows}
