"""SubtaskRepository — CRUD with Doc-24 nesting support."""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.models.subtask import Subtask
from app.models.subtask_dependency import SubtaskDependency
from app.models.subtask_resource import SubtaskResource
from app.repositories._cascade import clear_deleted, stamp_deleted
from app.utilities.positions import lock_position_scope
from app.utilities.timezones import now_ist


class SubtaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, subtask_id: str, *, include_deleted: bool = False) -> Optional[Subtask]:
        stmt = select(Subtask).where(Subtask.id == subtask_id)
        if not include_deleted:
            stmt = stmt.where(Subtask.deleted_at.is_(None))
        return self.db.execute(stmt).scalar_one_or_none()

    def _collect_descendant_ids(self, root_id: str, *, deleted_at) -> List[str]:
        """Walk parent_subtask_id downwards from ``root_id``, collecting
        every descendant whose ``deleted_at`` matches the predicate."""
        all_ids: List[str] = []
        frontier = [root_id]
        seen: set = set()
        while frontier:
            next_ids = list(self.db.execute(
                select(Subtask.id)
                .where(Subtask.parent_subtask_id.in_(frontier), deleted_at(Subtask))
            ).scalars())
            new_ids = [sid for sid in next_ids if sid not in seen]
            if not new_ids:
                break
            all_ids.extend(new_ids)
            seen.update(new_ids)
            frontier = new_ids
        return all_ids

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
            paginate(stmt, offset, page_size)
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
        lock_position_scope(self.db, f"subtask_pos:task:{task_id}")
        row = self.db.execute(
            select(func.coalesce(func.max(Subtask.position), 0))
            .where(Subtask.task_id == task_id)
            .where(Subtask.parent_subtask_id.is_(None))
            .where(Subtask.deleted_at.is_(None))
        ).scalar_one()
        return int(row) + 1

    def next_position_under_subtask(self, parent_subtask_id: str) -> int:
        lock_position_scope(self.db, f"subtask_pos:sub:{parent_subtask_id}")
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
        """Soft-delete this subtask + every nested descendant (recursive
        via parent_subtask_id) + the resource sidecars on the entire
        subtree."""
        descendant_ids = self._collect_descendant_ids(
            row.id, deleted_at=lambda m: m.deleted_at.is_(None),
        )
        all_ids = [row.id, *descendant_ids]
        now = now_ist()
        targets: List = [
            (SubtaskResource, [SubtaskResource.subtask_id.in_(all_ids)]),
        ]
        if descendant_ids:
            targets.append((Subtask, [Subtask.id.in_(descendant_ids)]))
        stamp_deleted(self.db, targets, when=now)
        row.deleted_at = now
        self.db.flush()
        return row

    def restore(self, row: Subtask) -> Subtask:
        """Restore this subtask + every nested descendant whose
        ``deleted_at`` matches this subtask's cascade-event timestamp."""
        cascade_ts = row.deleted_at
        if cascade_ts is None:
            return row
        descendant_ids = self._collect_descendant_ids(
            row.id, deleted_at=lambda m: m.deleted_at == cascade_ts,
        )
        all_ids = [row.id, *descendant_ids]
        targets: List = [
            (SubtaskResource, [SubtaskResource.subtask_id.in_(all_ids)]),
        ]
        if descendant_ids:
            targets.append((Subtask, [Subtask.id.in_(descendant_ids)]))
        clear_deleted(self.db, targets, cascade_ts=cascade_ts)
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
