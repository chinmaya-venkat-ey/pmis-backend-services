"""TaskRepository — CRUD + dependencies + 1:1 resource sidecar."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.models.task_dependency import TaskDependency
from app.models.task_resource import TaskResource


class TaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, task_id: str) -> Optional[Task]:
        return self.db.get(Task, task_id)

    def list_for_activity(
        self, activity_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Tuple[List[Task], int]:
        clauses = [Task.activity_id == activity_id]
        if not include_deleted:
            clauses.append(Task.deleted_at.is_(None))
        stmt = select(Task).where(and_(*clauses)).order_by(Task.position.asc())
        total = self.db.execute(
            select(func.count()).select_from(Task).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def next_position_for_activity(self, activity_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Task.position), 0))
            .where(Task.activity_id == activity_id)
            .where(Task.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def create(self, **kwargs) -> Task:
        row = Task(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Task, **kwargs) -> Task:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Task) -> Task:
        row.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return row

    def restore(self, row: Task) -> Task:
        row.deleted_at = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- dependencies

    def list_dependencies_for(self, task_id: str) -> List[str]:
        return list(self.db.execute(
            select(TaskDependency.to_task_id)
            .where(TaskDependency.from_task_id == task_id)
        ).scalars())

    def replace_dependencies(self, task_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            TaskDependency.__table__.delete().where(
                TaskDependency.from_task_id == task_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(TaskDependency(from_task_id=task_id, to_task_id=tid))
        self.db.flush()

    # --------------------------------------------------------------- resource sidecar

    def get_resource(self, task_id: str) -> Optional[TaskResource]:
        return self.db.execute(
            select(TaskResource)
            .where(TaskResource.task_id == task_id)
            .where(TaskResource.deleted_at.is_(None))
        ).scalar_one_or_none()

    def upsert_resource(self, *, task_id: str, project_id: str, **fields) -> TaskResource:
        existing = self.get_resource(task_id)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.db.flush()
            return existing
        row = TaskResource(task_id=task_id, project_id=project_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row
