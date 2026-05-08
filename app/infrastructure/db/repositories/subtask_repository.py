"""Subtask repository (with resource sub-entity ops)."""
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.subtask import SubtaskModel
from ..models.subtask_resource import SubtaskResourceModel
from ....domain.subtasks.subtask import Subtask
from ....domain.subtasks.subtask_resource import SubtaskResource
from ....shared.comments_attachments_cascade import (
    cascade_restore_comments_and_attachments,
    cascade_soft_delete_comments_and_attachments,
)


class SubtaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, s: SubtaskModel) -> Subtask:
        return Subtask(
            id=s.id,
            project_id=s.project_id,
            task_id=s.task_id,
            parent_subtask_id=getattr(s, "parent_subtask_id", None),
            name=s.name,
            description=s.description,
            type=s.type,
            start_date=s.start_date,
            end_date=s.end_date,
            actual_start_date=s.actual_start_date,
            actual_end_date=s.actual_end_date,
            position=s.position,
            resource_mode=s.resource_mode,
            resource_count=s.resource_count,
            status=getattr(s, "status", None),
            assigned_to=getattr(s, "assigned_to", None),
            created_at=s.created_at,
            updated_at=s.updated_at,
            created_by=s.created_by,
            updated_by=s.updated_by,
            deleted_at=s.deleted_at,
        )

    def _resource_to_domain(self, r: SubtaskResourceModel) -> SubtaskResource:
        return SubtaskResource(
            id=r.id,
            subtask_id=r.subtask_id,
            project_id=r.project_id,
            resource_name=r.resource_name,
            onboard_date=r.onboard_date,
            actual_onboard_date=r.actual_onboard_date,
            offboard_date=r.offboard_date,
            actual_offboard_date=r.actual_offboard_date,
            position=r.position,
            designation=r.designation,
            job_role=r.job_role,
            qualification=r.qualification,
            experience_years=r.experience_years,
            created_at=r.created_at,
            updated_at=r.updated_at,
            deleted_at=r.deleted_at,
        )

    # ---------- reads ----------

    def get_by_id(self, subtask_id: str, include_deleted: bool = False) -> Optional[Subtask]:
        q = self.db.query(SubtaskModel).filter(SubtaskModel.id == subtask_id)
        if not include_deleted:
            q = q.filter(SubtaskModel.deleted_at.is_(None))
        row = q.first()
        return self._to_domain(row) if row else None

    def get_model(self, subtask_id: str, include_deleted: bool = False) -> Optional[SubtaskModel]:
        q = self.db.query(SubtaskModel).filter(SubtaskModel.id == subtask_id)
        if not include_deleted:
            q = q.filter(SubtaskModel.deleted_at.is_(None))
        return q.first()

    def list_by_task(
        self, task_id: str, offset: int = 0, limit: int = 20,
        include_deleted: bool = False,
    ) -> Tuple[List[Subtask], int]:
        """List **TOP-LEVEL** subtasks under a task (paginated).

        Doc 28 fix: pre-fix, this returned every subtask in the subtree
        flat (because ``task_id`` is denormalized to the root task on
        every nested row). The FE used the result to render rows and
        every nested subtask appeared as a sibling of its parent.

        The fix scopes the query to ``parent_subtask_id IS NULL`` so
        ``total`` and pagination apply only to the top-level subtasks.
        Callers that need the full subtree (controller list + tree) load
        the nested rows separately via ``list_nested_under_task`` and
        embed them recursively.
        """
        base = (
            self.db.query(SubtaskModel)
            .filter(SubtaskModel.task_id == task_id)
            .filter(SubtaskModel.parent_subtask_id.is_(None))
        )
        if not include_deleted:
            base = base.filter(SubtaskModel.deleted_at.is_(None))
        total = base.with_entities(func.count(SubtaskModel.id)).scalar() or 0
        rows = (
            base.order_by(SubtaskModel.position.asc(), SubtaskModel.id.asc())
            .offset(offset).limit(limit).all()
        )
        return [self._to_domain(r) for r in rows], total

    def list_nested_under_task(
        self, task_id: str, include_deleted: bool = False,
    ) -> List[Subtask]:
        """Return EVERY nested subtask (parent_subtask_id IS NOT NULL)
        under a given task, flat. Caller groups by parent_subtask_id to
        embed children under each top-level row.

        Doc 28: the controller's list endpoint loads the top-level rows
        via ``list_by_task`` then this method to populate ``subtasks[]``
        recursively. One extra query per task — small constant cost,
        avoids N+1 across the subtree depth.
        """
        q = (
            self.db.query(SubtaskModel)
            .filter(SubtaskModel.task_id == task_id)
            .filter(SubtaskModel.parent_subtask_id.isnot(None))
        )
        if not include_deleted:
            q = q.filter(SubtaskModel.deleted_at.is_(None))
        rows = q.order_by(
            SubtaskModel.position.asc(), SubtaskModel.id.asc()
        ).all()
        return [self._to_domain(r) for r in rows]

    def next_position(self, task_id: str) -> int:
        """Next position for a TOP-LEVEL subtask (parent_subtask_id IS NULL).

        Doc 24: nested subtasks share ``task_id`` with their top-level
        ancestor, so we must explicitly exclude them here — otherwise the
        next-position would jump across the whole subtree.
        """
        cur = (
            self.db.query(func.max(SubtaskModel.position))
            .filter(SubtaskModel.task_id == task_id)
            .filter(SubtaskModel.parent_subtask_id.is_(None))
            .filter(SubtaskModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    def next_position_under_subtask(self, parent_subtask_id: str) -> int:
        """Next position for a subtask nested under another subtask."""
        cur = (
            self.db.query(func.max(SubtaskModel.position))
            .filter(SubtaskModel.parent_subtask_id == parent_subtask_id)
            .filter(SubtaskModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    def position_taken(self, task_id: str, position: int) -> bool:
        """True iff a live TOP-LEVEL subtask in ``task_id`` already
        occupies ``position`` (parent_subtask_id IS NULL — same scope as
        ``next_position``).

        Lets the create service auto-bump caller-supplied positions that
        would otherwise trip the unique index. See
        ``MilestoneRepository.position_taken`` for the same rationale.
        """
        return self.db.query(SubtaskModel.id).filter(
            SubtaskModel.task_id == task_id,
            SubtaskModel.parent_subtask_id.is_(None),
            SubtaskModel.position == position,
            SubtaskModel.deleted_at.is_(None),
        ).first() is not None

    def position_taken_under_subtask(
        self, parent_subtask_id: str, position: int,
    ) -> bool:
        """True iff a live nested subtask under ``parent_subtask_id``
        already occupies ``position`` (same scope as
        ``next_position_under_subtask``)."""
        return self.db.query(SubtaskModel.id).filter(
            SubtaskModel.parent_subtask_id == parent_subtask_id,
            SubtaskModel.position == position,
            SubtaskModel.deleted_at.is_(None),
        ).first() is not None

    def ancestors(self, subtask_id: str) -> List[SubtaskModel]:
        """Return the subtask's ancestor chain, root-first.

        For a top-level subtask returns ``[]``. For a nested subtask
        returns ``[grandparent, parent]`` (excluding the subtask itself).
        Walks ``parent_subtask_id`` until NULL. Does not filter by
        ``deleted_at`` — soft-deleted ancestors still count for depth so
        a restore preserves the path.
        """
        chain: List[SubtaskModel] = []
        cursor = self.get_model(subtask_id, include_deleted=True)
        if cursor is None:
            return chain
        # Walk parents up to root.
        seen = {cursor.id}
        while cursor.parent_subtask_id is not None:
            parent = self.get_model(
                cursor.parent_subtask_id, include_deleted=True,
            )
            if parent is None or parent.id in seen:
                break
            seen.add(parent.id)
            chain.append(parent)
            cursor = parent
        chain.reverse()  # root-first
        return chain

    def descendant_ids(self, root_subtask_id: str) -> List[str]:
        """Iterative BFS over ``parent_subtask_id`` from this subtask.

        Returns every subtask id in the subtree rooted at the given id,
        including the root, in BFS order. Iterates over LIVE rows only
        (already-deleted descendants are not re-touched on cascade).
        """
        out: List[str] = []
        frontier: deque = deque([root_subtask_id])
        seen = {root_subtask_id}
        while frontier:
            current = frontier.popleft()
            out.append(current)
            children = (
                self.db.query(SubtaskModel.id)
                .filter(SubtaskModel.parent_subtask_id == current)
                .filter(SubtaskModel.deleted_at.is_(None))
                .all()
            )
            for (cid,) in children:
                if cid not in seen:
                    seen.add(cid)
                    frontier.append(cid)
        return out

    def get_live_resource(self, subtask_id: str) -> Optional[SubtaskResource]:
        row = (
            self.db.query(SubtaskResourceModel)
            .filter(SubtaskResourceModel.subtask_id == subtask_id)
            .filter(SubtaskResourceModel.deleted_at.is_(None))
            .first()
        )
        return self._resource_to_domain(row) if row else None

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, task_id: str, name: str, description: Optional[str],
        type: str, start_date: datetime, end_date: datetime,
        actual_start_date: Optional[datetime], actual_end_date: Optional[datetime],
        position: int, created_by: Optional[str],
        resource_mode: Optional[str] = None,
        resource_count: Optional[int] = None,
        parent_subtask_id: Optional[str] = None,
        status: Optional[str] = None,
        # Doc 41 follow-up: optional assignee user UUID.
        assigned_to: Optional[str] = None,
    ) -> Subtask:
        s = SubtaskModel(
            project_id=project_id,
            task_id=task_id,
            parent_subtask_id=parent_subtask_id,
            name=name,
            description=description,
            type=type,
            start_date=start_date,
            end_date=end_date,
            actual_start_date=actual_start_date,
            actual_end_date=actual_end_date,
            position=position,
            resource_mode=resource_mode,
            resource_count=resource_count,
            status=status,
            assigned_to=assigned_to,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(s)
        self.db.flush()
        return self._to_domain(s)

    def update(self, subtask_id: str, *, updates: dict, updated_by: Optional[str]) -> Subtask:
        s = self.get_model(subtask_id)
        if s is None:
            raise LookupError(f"Subtask {subtask_id} not found")
        for k, v in updates.items():
            setattr(s, k, v)
        s.updated_by = updated_by
        self.db.flush()
        return self._to_domain(s)

    # ---------- resource sub-entity ----------

    def insert_resource(self, *, subtask_id: str, project_id: str, data: dict) -> SubtaskResource:
        r = SubtaskResourceModel(
            subtask_id=subtask_id,
            project_id=project_id,
            resource_name=data["resource_name"],
            onboard_date=data.get("onboard_date"),
            actual_onboard_date=data.get("actual_onboard_date"),
            offboard_date=data.get("offboard_date"),
            actual_offboard_date=data.get("actual_offboard_date"),
            position=data.get("position"),
            designation=data.get("designation"),
            job_role=data.get("job_role"),
            qualification=data.get("qualification"),
            experience_years=data.get("experience_years"),
        )
        self.db.add(r)
        self.db.flush()
        return self._resource_to_domain(r)

    def upsert_resource(self, *, subtask_id: str, project_id: str, data: dict) -> SubtaskResource:
        existing = (
            self.db.query(SubtaskResourceModel)
            .filter(
                SubtaskResourceModel.subtask_id == subtask_id,
                SubtaskResourceModel.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            return self.insert_resource(subtask_id=subtask_id, project_id=project_id, data=data)
        for field in (
            "resource_name", "onboard_date", "actual_onboard_date",
            "offboard_date", "actual_offboard_date",
            "position", "designation", "job_role", "qualification", "experience_years",
        ):
            if field in data:
                setattr(existing, field, data[field])
        existing.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return self._resource_to_domain(existing)

    def soft_delete_live_resource(self, subtask_id: str) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            update(SubtaskResourceModel)
            .where(
                SubtaskResourceModel.subtask_id == subtask_id,
                SubtaskResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )

    # ---------- delete (subtask + its descendant subtree, doc 24) ----------

    def soft_delete(self, subtask_id: str, deleted_by: Optional[str]) -> List[str]:
        """Soft-delete a subtask + every nested descendant subtask.

        Doc 24: with nesting, deleting a subtask must cascade to all
        descendants (and their resource rows). Returns the full list of
        soft-deleted subtask ids in BFS order — callers use this to
        cascade dependency-edge wipes (one call per id is fine; the
        ``DependencyRepository.cascade_remove_subtask_targets`` helper
        is idempotent).
        """
        now = datetime.now(timezone.utc)
        ids = self.descendant_ids(subtask_id)
        if not ids:
            return []
        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.subtask_id.in_(ids),
            SubtaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.id.in_(ids),
            SubtaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))

        # Doc 34: cascade comments + attachments anchored at any of the
        # subtasks we just soft-deleted (every nested descendant id is
        # in ``ids`` already, BFS order from descendant_ids).
        cascade_soft_delete_comments_and_attachments(
            self.db,
            targets=[("subtask", ids)],
            deleted_by=deleted_by,
            now=now,
        )

        self.db.commit()
        return ids

    def restore(self, subtask_id: str, restored_by: Optional[int]) -> Subtask:
        """
        Restore the subtask + every nested-descendant subtask /
        resource / comment / attachment that was soft-deleted as part
        of the same cascade event (doc 34). Dep edges are NOT
        auto-restored.

        Identification: every row stamped by ``soft_delete`` shares the
        same ``deleted_at`` timestamp (microsecond-precise via
        ``datetime.now()``). BFS down ``parent_subtask_id`` collects
        every descendant whose ``deleted_at`` matches.
        """
        s = self.get_model(subtask_id, include_deleted=True)
        if s is None:
            raise LookupError(f"Subtask {subtask_id} not found")
        if s.deleted_at is None:
            return self._to_domain(s)

        cascade_ts = s.deleted_at
        now = datetime.now(timezone.utc)

        all_ids = {subtask_id}
        queue = deque([subtask_id])
        while queue:
            parent = queue.popleft()
            children = [
                r[0] for r in self.db.execute(
                    select(SubtaskModel.id).where(
                        SubtaskModel.parent_subtask_id == parent,
                        SubtaskModel.deleted_at == cascade_ts,
                    )
                ).all()
            ]
            for cid in children:
                if cid not in all_ids:
                    all_ids.add(cid)
                    queue.append(cid)

        id_list = list(all_ids)
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.id.in_(id_list),
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))

        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.subtask_id.in_(id_list),
            SubtaskResourceModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now))

        cascade_restore_comments_and_attachments(
            self.db,
            targets=[("subtask", id_list)],
            cascade_deleted_at=cascade_ts,
        )

        self.db.commit()
        self.db.refresh(s)
        return self._to_domain(s)
