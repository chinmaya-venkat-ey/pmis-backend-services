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
        """Return (from_activity_id, to_activity_id) pairs where BOTH
        endpoints are activities in this project.

        Semantic: from_activity_id DEPENDS ON to_activity_id
        i.e. to_activity_id is the predecessor that must finish first.

        Cross-project dependency edges (target in another project) are
        EXCLUDED so the critical-path graph never references a node outside
        its own project node set — keeping CPA correct and crash-proof.
        Critical path is a per-project schedule view; cross-project links are
        honoured by the completion / cycle / date gates, not here.
        """
        in_project = select(Activity.id).where(
            and_(
                Activity.project_id == project_id,
                Activity.deleted_at.is_(None),
            )
        )
        rows = self.db.execute(
            select(
                ActivityDependency.from_activity_id,
                ActivityDependency.to_activity_id,
            ).where(
                and_(
                    ActivityDependency.from_activity_id.in_(in_project),
                    ActivityDependency.to_activity_id.in_(in_project),
                )
            )
        ).mappings().all()
        return [(r["from_activity_id"], r["to_activity_id"]) for r in rows]

    def get_cross_project_predecessors(
        self, project_id: str
    ) -> Tuple[List[Tuple[str, str]], Dict[str, Dict[str, Any]]]:
        """Cross-project predecessor edges + the external predecessor activities.

        Returns ``(edges, external_acts)``:
          * ``edges``: ``[(from_id, to_id)]`` where ``from`` (the dependent) is
            a live activity in THIS project and ``to`` (the predecessor) is a
            live, non-meeting activity in ANOTHER project.
          * ``external_acts``: ``{to_id: {...}}`` carrying the predecessor's
            duration fields + project name + positions.

        These are folded into the CPM graph as constraint nodes so the
        UNCHANGED ``ES = max(EF of predecessors) + 1`` formula pulls the
        external predecessor's finish into the dependent's start. They are kept
        OUT of the per-project schedule/flow output and surfaced only in
        ``depends_on`` (flagged ``cross_project``).
        """
        from app.models.project import Project
        in_project = select(Activity.id).where(
            and_(
                Activity.project_id == project_id,
                Activity.deleted_at.is_(None),
            )
        )
        rows = self.db.execute(
            select(
                ActivityDependency.from_activity_id,
                ActivityDependency.to_activity_id,
                Activity.name,
                Activity.milestone_id,
                Activity.position,
                Activity.status,
                Activity.start_date,
                Activity.end_date,
                Activity.actual_start_date,
                Activity.actual_end_date,
                Milestone.position.label("milestone_position"),
                Project.name.label("project_name"),
            )
            .join(Activity, Activity.id == ActivityDependency.to_activity_id)
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .join(Project, Project.id == Activity.project_id)
            .where(
                and_(
                    ActivityDependency.from_activity_id.in_(in_project),
                    ActivityDependency.to_activity_id.not_in(in_project),
                    Activity.deleted_at.is_(None),
                    Milestone.is_meeting.is_(False),
                )
            )
        ).mappings().all()
        edges: List[Tuple[str, str]] = []
        external_acts: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            edges.append((r["from_activity_id"], r["to_activity_id"]))
            tid = r["to_activity_id"]
            if tid not in external_acts:
                external_acts[tid] = {
                    "id": tid,
                    "name": r["name"],
                    "milestone_id": r["milestone_id"],
                    "position": r["position"],
                    "status": r["status"],
                    "start_date": r["start_date"],
                    "end_date": r["end_date"],
                    "actual_start_date": r["actual_start_date"],
                    "actual_end_date": r["actual_end_date"],
                    "milestone_position": r["milestone_position"],
                    "project_name": r["project_name"],
                    # Markers for the service: keep out of output, flag in deps.
                    "_cross_project": True,
                    "_project_name": r["project_name"],
                }
        return edges, external_acts
