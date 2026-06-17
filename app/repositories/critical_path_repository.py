"""CriticalPathRepository — read-only queries for CPA.

Fetches activities, milestones, and dependency edges for a project
in three queries (activities, milestones, dependencies) and returns
plain dicts so the service layer can work without ORM session concerns.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.activity_dependency import ActivityDependency
from app.models.milestone import Milestone


class CriticalPathRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_project_activities(self, project_id: str) -> List[Dict[str, Any]]:
        # Skip activities whose parent milestone is_meeting=True — meeting
        # activities aren't part of the project's critical-path scope.
        rows = self.db.execute(
            select(
                Activity.id,
                Activity.name,
                Activity.milestone_id,
                Activity.position,
                Activity.status,
                Activity.start_date,
                Activity.end_date,
                Activity.actual_start_date,
                Activity.actual_end_date,
            )
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(
                and_(
                    Activity.project_id == project_id,
                    Activity.deleted_at.is_(None),
                    Milestone.is_meeting.is_(False),
                )
            ).order_by(Activity.milestone_id, Activity.position)
        ).mappings().all()
        return [dict(r) for r in rows]

    def get_project_milestones(self, project_id: str) -> Dict[str, Dict[str, Any]]:
        # Exclude the meeting milestone — CPM doesn't model meetings.
        rows = self.db.execute(
            select(
                Milestone.id,
                Milestone.name,
                Milestone.position,
            ).where(
                and_(
                    Milestone.project_id == project_id,
                    Milestone.deleted_at.is_(None),
                    Milestone.is_meeting.is_(False),
                )
            ).order_by(Milestone.position)
        ).mappings().all()
        return {r["id"]: dict(r) for r in rows}

    def get_activity_dependencies(
        self, project_id: str
    ) -> List[Tuple[str, str]]:
        """Return (from_activity_id, to_activity_id) pairs.

        Semantic: from_activity_id DEPENDS ON to_activity_id
        i.e. to_activity_id is the predecessor that must finish first.
        """
        rows = self.db.execute(
            select(
                ActivityDependency.from_activity_id,
                ActivityDependency.to_activity_id,
            ).where(
                ActivityDependency.from_activity_id.in_(
                    select(Activity.id).where(
                        and_(
                            Activity.project_id == project_id,
                            Activity.deleted_at.is_(None),
                        )
                    )
                )
            )
        ).mappings().all()
        return [(r["from_activity_id"], r["to_activity_id"]) for r in rows]
