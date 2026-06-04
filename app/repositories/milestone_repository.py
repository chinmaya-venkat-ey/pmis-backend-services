"""MilestoneRepository — CRUD + position management for project.milestones."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.activity_resource import ActivityResource
from app.models.milestone import Milestone
from app.models.milestone_dependency import MilestoneDependency
from app.models.milestone_vendor import MilestoneVendor
from app.models.subtask import Subtask
from app.models.subtask_resource import SubtaskResource
from app.models.task import Task
from app.models.task_resource import TaskResource
from app.repositories._cascade import clear_deleted, stamp_deleted
from app.utilities.timezones import now_ist


class MilestoneRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, milestone_id: str, *, include_deleted: bool = False) -> Optional[Milestone]:
        stmt = select(Milestone).where(Milestone.id == milestone_id)
        if not include_deleted:
            stmt = stmt.where(Milestone.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def _snapshot_subtree_ids(self, milestone_id: str, *, deleted_at):
        """Return (activity_ids, task_ids, subtask_ids) under this milestone
        whose ``deleted_at`` matches the predicate. Used by both soft-delete
        (deleted_at IS NULL → live subtree) and restore (deleted_at == cascade_ts
        → previously-cascaded subtree)."""
        activity_ids = list(self.db.execute(
            select(Activity.id)
            .where(Activity.milestone_id == milestone_id, deleted_at(Activity))
        ).scalars())
        task_ids = list(self.db.execute(
            select(Task.id)
            .where(Task.activity_id.in_(activity_ids), deleted_at(Task))
        ).scalars()) if activity_ids else []
        subtask_ids = list(self.db.execute(
            select(Subtask.id)
            .where(Subtask.task_id.in_(task_ids), deleted_at(Subtask))
        ).scalars()) if task_ids else []
        return activity_ids, task_ids, subtask_ids

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
        include_meetings: bool = False,
    ) -> Tuple[List[Milestone], int]:
        """List milestones under a project. By default, meeting milestones
        (``is_meeting = True``) are filtered out — they're auto-managed
        containers for meeting-type activities and shouldn't appear in
        normal milestone-level surfaces. Set ``include_meetings=True``
        to include them (used by the project-detail controller when it
        needs to resolve ``meeting_milestone_id``)."""
        clauses = [Milestone.project_id == project_id]
        if not include_deleted:
            clauses.append(Milestone.deleted_at.is_(None))
        if not include_meetings:
            clauses.append(Milestone.is_meeting.is_(False))
        stmt = select(Milestone).where(and_(*clauses)).order_by(Milestone.position.asc())
        count_stmt = select(func.count()).select_from(Milestone).where(and_(*clauses))
        total = self.db.execute(count_stmt).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def get_meeting_milestone_id(self, project_id: str) -> Optional[str]:
        """Return the id of the live meeting milestone for a project,
        or None if it doesn't exist yet. There is at most one (enforced
        by the partial unique index ``uq_milestones_one_meeting_per_project``)."""
        return self.db.execute(
            select(Milestone.id)
            .where(Milestone.project_id == project_id)
            .where(Milestone.is_meeting.is_(True))
            .where(Milestone.deleted_at.is_(None))
            .limit(1)
        ).scalar_one_or_none()

    def next_position_for_project(self, project_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Milestone.position), 0))
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> Milestone:
        row = Milestone(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Milestone, **kwargs) -> Milestone:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Milestone) -> Milestone:
        """Soft-delete this milestone + cascade to its activities, tasks,
        subtasks and resource sidecars."""
        activity_ids, task_ids, subtask_ids = self._snapshot_subtree_ids(
            row.id, deleted_at=lambda m: m.deleted_at.is_(None),
        )
        now = now_ist()
        targets: List = []
        if activity_ids:
            targets += [
                (ActivityResource, [ActivityResource.activity_id.in_(activity_ids)]),
                (Activity, [Activity.id.in_(activity_ids)]),
            ]
        if task_ids:
            targets += [
                (TaskResource, [TaskResource.task_id.in_(task_ids)]),
                (Task, [Task.id.in_(task_ids)]),
            ]
        if subtask_ids:
            targets += [
                (SubtaskResource, [SubtaskResource.subtask_id.in_(subtask_ids)]),
                (Subtask, [Subtask.id.in_(subtask_ids)]),
            ]
        stamp_deleted(self.db, targets, when=now)
        row.deleted_at = now
        self.db.flush()
        return row

    def restore(self, row: Milestone) -> Milestone:
        """Restore this milestone + every descendant whose ``deleted_at``
        matches this milestone's cascade-event timestamp."""
        cascade_ts = row.deleted_at
        if cascade_ts is None:
            return row
        activity_ids, task_ids, subtask_ids = self._snapshot_subtree_ids(
            row.id, deleted_at=lambda m: m.deleted_at == cascade_ts,
        )
        targets: List = []
        if activity_ids:
            targets += [
                (ActivityResource, [ActivityResource.activity_id.in_(activity_ids)]),
                (Activity, [Activity.id.in_(activity_ids)]),
            ]
        if task_ids:
            targets += [
                (TaskResource, [TaskResource.task_id.in_(task_ids)]),
                (Task, [Task.id.in_(task_ids)]),
            ]
        if subtask_ids:
            targets += [
                (SubtaskResource, [SubtaskResource.subtask_id.in_(subtask_ids)]),
                (Subtask, [Subtask.id.in_(subtask_ids)]),
            ]
        clear_deleted(self.db, targets, cascade_ts=cascade_ts)
        row.deleted_at = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- dependencies

    def list_dependencies_for(self, milestone_id: str) -> List[str]:
        return list(self.db.execute(
            select(MilestoneDependency.to_milestone_id)
            .where(MilestoneDependency.from_milestone_id == milestone_id)
        ).scalars())

    def replace_dependencies(self, milestone_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            MilestoneDependency.__table__.delete().where(
                MilestoneDependency.from_milestone_id == milestone_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(MilestoneDependency(
                from_milestone_id=milestone_id, to_milestone_id=tid,
            ))
        self.db.flush()

    # --------------------------------------------------------------- vendors

    def list_vendors_for(self, milestone_id: str) -> List[str]:
        return list(self.db.execute(
            select(MilestoneVendor.vendor_id)
            .where(MilestoneVendor.milestone_id == milestone_id)
        ).scalars())

    def set_vendor_mapping(self, milestone_id: str, vendor_ids: List[str]) -> None:
        self.db.execute(
            MilestoneVendor.__table__.delete().where(
                MilestoneVendor.milestone_id == milestone_id
            )
        )
        for vid in vendor_ids:
            self.db.add(MilestoneVendor(milestone_id=milestone_id, vendor_id=vid))
        self.db.flush()
