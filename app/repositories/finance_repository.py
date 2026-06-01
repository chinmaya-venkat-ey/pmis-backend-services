"""FinanceRepository — read-side helpers for project finance.

Pulls the rolled-up CCN consumption (sum of ccn_value across every live
milestone + activity with ``category='ccn'``) and the per-row list used
to populate the Finance page's "CCN items" table.

No write methods — finance field writes ride the existing
``ProjectRepository.update`` path (the FinanceService just calls into
that with the touched fields).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.milestone import Milestone


class FinanceRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------- read-only

    def sum_ccn_used(self, project_id: str) -> Decimal:
        """Total CCN value consumed across live milestones + activities."""
        milestone_sum = self.db.execute(
            select(func.coalesce(func.sum(Milestone.ccn_value), 0))
            .where(Milestone.project_id == project_id)
            .where(Milestone.category == "ccn")
            .where(Milestone.deleted_at.is_(None))
        ).scalar_one()
        activity_sum = self.db.execute(
            select(func.coalesce(func.sum(Activity.ccn_value), 0))
            .where(Activity.project_id == project_id)
            .where(Activity.category == "ccn")
            .where(Activity.deleted_at.is_(None))
        ).scalar_one()
        return Decimal(milestone_sum) + Decimal(activity_sum)

    def list_ccn_milestones(
        self, project_id: str,
    ) -> List[Tuple[str, str, int, Decimal, object]]:
        """Return (id, name, position, ccn_value, created_at) for live
        CCN milestones, ordered by position."""
        rows = self.db.execute(
            select(
                Milestone.id, Milestone.name, Milestone.position,
                Milestone.ccn_value, Milestone.created_at,
            )
            .where(Milestone.project_id == project_id)
            .where(Milestone.category == "ccn")
            .where(Milestone.deleted_at.is_(None))
            .order_by(Milestone.position.asc())
        ).all()
        return [tuple(r) for r in rows]

    def list_ccn_activities(
        self, project_id: str,
    ) -> List[Tuple[str, str, int, int, Decimal, object]]:
        """Return (id, name, milestone_position, activity_position,
        ccn_value, created_at) for live CCN activities, ordered by
        (milestone_position, activity_position) — matches the FE's
        ``A{m}.{a}`` label ordering."""
        rows = self.db.execute(
            select(
                Activity.id, Activity.name,
                Milestone.position.label("milestone_position"),
                Activity.position.label("activity_position"),
                Activity.ccn_value, Activity.created_at,
            )
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Activity.project_id == project_id)
            .where(Activity.category == "ccn")
            .where(Activity.deleted_at.is_(None))
            .where(Milestone.deleted_at.is_(None))
            .order_by(
                Milestone.position.asc(), Activity.position.asc(),
            )
        ).all()
        return [tuple(r) for r in rows]
