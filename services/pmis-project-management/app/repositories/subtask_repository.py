"""SubtaskRepository — CRUD with Doc-24 nesting support."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.subtask import Subtask
from app.models.subtask_dependency import SubtaskDependency
from app.models.subtask_resource import SubtaskResource


class SubtaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, subtask_id: str) -> Optional[Subtask]:
        return self.db.get(Subtask, subtask_id)

    def list_for_task(
        self, task_id: str, *,
        offset: int = 1, page_size: int = 100, include_deleted: bool = False,
        top_level_only: bool = False,
    ) -> Tuple[List[Subtask], int]:
        clauses = [Subtask.task_id == task_id]
        if not include_deleted:
            clauses.append(Subtask.deleted_at.is_(None))
        if top_level_only:
            clauses.append(Subtask.parent_subtask_id.is_(None))
        stmt = select(Subtask).where(and_(*clauses)).order_by(
            Subtask.parent_subtask_id.asc().nullsfirst(), Subtask.position.asc(),
        )
        total = self.db.execute(
            select(func.count()).select_from(Subtask).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def list_children_of(self, parent_subtask_id: str) -> List[Subtask]:
        return list(self.db.execute(
            select(Subtask)
            .where(Subtask.parent_subtask_id == parent_subtask_id)
            .where(Subtask.deleted_at.is_(None))
            .order_by(Subtask.position.asc())
        ).scalars())

    def next_position_under_task(self, task_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Subtask.position), 0))
            .where(Subtask.task_id == task_id)
            .where(Subtask.parent_subtask_id.is_(None))
            .where(Subtask.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def next_position_under_subtask(self, parent_subtask_id: str) -> int:
        row = self.db.execute(
            select(func.coalesce(func.max(Subtask.position), 0))
            .where(Subtask.parent_subtask_id == parent_subtask_id)
            .where(Subtask.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def nesting_depth(self, subtask_id: str) -> int:
        """Walk parent_subtask_id chain up. Returns 1 for top-level."""
        depth = 1
        current = self.get_by_id(subtask_id)
        while current is not None and current.parent_subtask_id is not None:
            depth += 1
            current = self.get_by_id(current.parent_subtask_id)
            if depth > 100:  # cycle protection
                break
        return depth

    def create(self, **kwargs) -> Subtask:
        row = Subtask(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: Subtask, **kwargs) -> Subtask:
        for k, v in kwargs.items():
            setattr(row, k, v)
        self.db.flush()
        return row

    def soft_delete(self, row: Subtask) -> Subtask:
        row.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return row

    def restore(self, row: Subtask) -> Subtask:
        row.deleted_at = None
        self.db.flush()
        return row

    # --------------------------------------------------------------- dependencies

    def list_dependencies_for(self, subtask_id: str) -> List[str]:
        return list(self.db.execute(
            select(SubtaskDependency.to_subtask_id)
            .where(SubtaskDependency.from_subtask_id == subtask_id)
        ).scalars())

    def replace_dependencies(self, subtask_id: str, depends_on_ids: List[str]) -> None:
        self.db.execute(
            SubtaskDependency.__table__.delete().where(
                SubtaskDependency.from_subtask_id == subtask_id
            )
        )
        for tid in depends_on_ids:
            self.db.add(SubtaskDependency(from_subtask_id=subtask_id, to_subtask_id=tid))
        self.db.flush()

    # --------------------------------------------------------------- resource sidecar

    def get_resource(self, subtask_id: str) -> Optional[SubtaskResource]:
        return self.db.execute(
            select(SubtaskResource)
            .where(SubtaskResource.subtask_id == subtask_id)
            .where(SubtaskResource.deleted_at.is_(None))
        ).scalar_one_or_none()

    def upsert_resource(self, *, subtask_id: str, project_id: str, **fields) -> SubtaskResource:
        existing = self.get_resource(subtask_id)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.db.flush()
            return existing
        row = SubtaskResource(subtask_id=subtask_id, project_id=project_id, **fields)
        self.db.add(row)
        self.db.flush()
        return row
