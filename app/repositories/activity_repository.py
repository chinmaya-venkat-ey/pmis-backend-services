"""ActivityRepository — CRUD + dependencies + 1:1 resource sidecar +
1:many planned-resource allocations."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.models.activity import Activity
from app.models.activity_dependency import ActivityDependency
from app.models.activity_planned_resource import ActivityPlannedResource
from app.models.activity_resource import ActivityResource
from app.models.subtask import Subtask
from app.models.subtask_resource import SubtaskResource
from app.models.task import Task
from app.models.task_resource import TaskResource
from app.repositories._cascade import clear_deleted, stamp_deleted
from app.utilities.positions import lock_position_scope
from app.utilities.timezones import now_ist


class ActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, activity_id: str, *, include_deleted: bool = False) -> Optional[Activity]:
        stmt = select(Activity).where(Activity.id == activity_id)
        if not include_deleted:
            stmt = stmt.where(Activity.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def _snapshot_subtree_ids(self, activity_id: str, *, deleted_at):
        """Return (task_ids, subtask_ids) under this activity whose
        ``deleted_at`` matches the predicate."""
        task_ids = list(self.db.execute(
            select(Task.id)
            .where(Task.activity_id == activity_id, deleted_at(Task))
        ).scalars())
        subtask_ids = list(self.db.execute(
            select(Subtask.id)
            .where(Subtask.task_id.in_(task_ids), deleted_at(Subtask))
        ).scalars()) if task_ids else []
        return task_ids, subtask_ids

    def list_for_milestone(
        self, milestone_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Tuple[List[Activity], int]:
        clauses = [Activity.milestone_id == milestone_id]
        if not include_deleted:
            clauses.append(Activity.deleted_at.is_(None))
        stmt = select(Activity).where(and_(*clauses)).order_by(Activity.position.asc())
        total = self.db.execute(
            select(func.count()).select_from(Activity).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            paginate(stmt, offset, page_size)
        ).scalars().all()
        return list(rows), total

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 100, include_deleted: bool = False,
    ) -> Tuple[List[Activity], int]:
        clauses = [Activity.project_id == project_id]
        if not include_deleted:
            clauses.append(Activity.deleted_at.is_(None))
        stmt = select(Activity).where(and_(*clauses)).order_by(
            Activity.milestone_id.asc(), Activity.position.asc()
        )
        total = self.db.execute(
            select(func.count()).select_from(Activity).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            paginate(stmt, offset, page_size)
        ).scalars().all()
        return list(rows), total

    def list_by_milestone_ids(self, milestone_ids):
        """{milestone_id: [live activities...]} ordered by position — bulk, no
        N+1. Used to enrich partial-payment milestones' payment terms."""
        out = {}
        if not milestone_ids:
            return out
        rows = self.db.execute(
            select(Activity)
            .where(Activity.milestone_id.in_(list(milestone_ids)))
            .where(Activity.deleted_at.is_(None))
            .order_by(Activity.milestone_id.asc(), Activity.position.asc())
        ).scalars().all()
        for r in rows:
            out.setdefault(r.milestone_id, []).append(r)
        return out

    def next_position_for_milestone(self, milestone_id: str) -> int:
        lock_position_scope(self.db, f"activity_pos:{milestone_id}")
        row = self.db.execute(
            select(func.coalesce(func.max(Activity.position), 0))
            .where(Activity.milestone_id == milestone_id)
            .where(Activity.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> Activity:
        row = Activity(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Activity, **kwargs) -> Activity:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Activity) -> Activity:
        """Soft-delete the activity + cascade to its tasks, subtasks and
        all resource sidecars under the subtree."""
        task_ids, subtask_ids = self._snapshot_subtree_ids(
            row.id, deleted_at=lambda m: m.deleted_at.is_(None),
        )
        now = now_ist()
        targets: List = [
            (ActivityResource, [ActivityResource.activity_id == row.id]),
            (ActivityPlannedResource, [ActivityPlannedResource.activity_id == row.id]),
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

    def restore(self, row: Activity) -> Activity:
        """Restore the activity + every descendant whose ``deleted_at``
        matches this activity's cascade-event timestamp."""
        cascade_ts = row.deleted_at
        if cascade_ts is None:
            return row
        task_ids, subtask_ids = self._snapshot_subtree_ids(
            row.id, deleted_at=lambda m: m.deleted_at == cascade_ts,
        )
        targets: List = [
            (ActivityResource, [ActivityResource.activity_id == row.id]),
            (ActivityPlannedResource, [ActivityPlannedResource.activity_id == row.id]),
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

    def list_dependencies_for(self, activity_id: str) -> List[str]:
        return list(self.db.execute(
            select(ActivityDependency.to_activity_id)
            .where(ActivityDependency.from_activity_id == activity_id)
        ).scalars())

    def replace_dependencies(self, activity_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            ActivityDependency.__table__.delete().where(
                ActivityDependency.from_activity_id == activity_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(ActivityDependency(
                from_activity_id=activity_id, to_activity_id=tid,
            ))
        self.db.flush()

    # --------------------------------------------------------------- resource sidecar

    def get_resource(self, activity_id: str) -> Optional[ActivityResource]:
        return self.db.execute(
            select(ActivityResource)
            .where(ActivityResource.activity_id == activity_id)
            .where(ActivityResource.deleted_at.is_(None))
        ).scalar_one_or_none()

    def upsert_resource(self, *, activity_id: str, project_id: str, **fields) -> ActivityResource:
        existing = self.get_resource(activity_id)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.db.flush()
            return existing
        row = ActivityResource(activity_id=activity_id, project_id=project_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row

    # ------------------------------------------------- planned-resource allocations

    def list_planned_resources(self, activity_id: str) -> List[ActivityPlannedResource]:
        return list(self.db.execute(
            select(ActivityPlannedResource)
            .where(ActivityPlannedResource.activity_id == activity_id)
            .where(ActivityPlannedResource.deleted_at.is_(None))
            .order_by(ActivityPlannedResource.position.asc())
        ).scalars())

    def list_planned_resources_for_activities(
        self, activity_ids: List[str],
    ) -> List[ActivityPlannedResource]:
        if not activity_ids:
            return []
        return list(self.db.execute(
            select(ActivityPlannedResource)
            .where(ActivityPlannedResource.activity_id.in_(activity_ids))
            .where(ActivityPlannedResource.deleted_at.is_(None))
            .order_by(ActivityPlannedResource.position.asc())
        ).scalars())

    def replace_planned_resources(
        self, activity_id: str, project_id: str, rows: List[dict], *,
        actor_user_id: Optional[str] = None,
    ) -> None:
        """Wholesale-replace an activity's allocation rows (hard delete + insert).
        ``rows`` = [{designation, quantity, duration}, ...] in display order."""
        self.db.execute(
            ActivityPlannedResource.__table__.delete().where(
                ActivityPlannedResource.activity_id == activity_id
            )
        )
        for pos, r in enumerate(rows or [], start=1):
            self.db.add(ActivityPlannedResource(
                activity_id=activity_id, project_id=project_id,
                designation=r["designation"], quantity=r["quantity"],
                duration=r["duration"],
                planned_deployment_date=r.get("planned_deployment_date"),
                monthly_rate=r.get("monthly_rate"),
                computed_cost=r.get("computed_cost"),
                resource_classification=r.get("resource_classification", "planned"),
                position=pos,
                created_by=actor_user_id, updated_by=actor_user_id,
            ))
        self.db.flush()
