"""Dependency repository.

Centralizes all reads/writes against the three association tables:
- activity_dependencies (source_activity, target_activity)
- task_dependencies     (source_task, target_task)
- subtask_dependencies  (source_subtask, target_subtask)

Soft-delete semantics
---------------------
Every write is a SOFT delete. Rows are never physically removed:
- Reads always filter ``deleted_at IS NULL``.
- "Removing" an edge sets ``deleted_at`` and ``deleted_by`` on the live row.
- Re-adding a previously removed edge inserts a NEW row (fresh UUID id);
  the partial unique on ``(source, target) WHERE deleted_at IS NULL``
  allows the two rows (one dead, one fresh-live) to coexist.
- All replace-list writers (``set_*_dependencies``) use this pattern:
  diff the current live set against the desired set; soft-delete removed,
  insert fresh rows for added.
- Cascade on entity delete (``cascade_remove_*``) soft-deletes every live
  row pointing at or leaving the target.

All writes ``flush`` but do NOT commit. Caller owns the transaction.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models.activity import ActivityModel
from ..models.activity_dependency import ActivityDependencyModel
from ..models.milestone import MilestoneModel
from ..models.milestone_dependency import MilestoneDependencyModel
from ..models.subtask import SubtaskModel
from ..models.subtask_dependency import SubtaskDependencyModel
from ..models.task import TaskModel
from ..models.task_dependency import TaskDependencyModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DependencyRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------
    # Milestone dependencies
    # -------------------------------------------------------------------

    def list_milestone_dependencies(self, source_milestone_id: str) -> List[str]:
        """Target ids this source depends on (live edges only), sorted."""
        rows = (
            self.db.query(MilestoneDependencyModel.target_milestone_id)
            .filter(MilestoneDependencyModel.source_milestone_id == source_milestone_id)
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .all()
        )
        return sorted(r[0] for r in rows)

    def set_milestone_dependencies(
        self,
        source_milestone_id: str,
        project_id: str,
        target_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        """Replace the source milestone's LIVE dependency target list.

        Targets missing from the new list are soft-deleted; new targets
        get fresh rows. Does NOT commit.
        """
        targets = list(dict.fromkeys(target_ids))
        existing_live = set(
            r[0]
            for r in self.db.query(MilestoneDependencyModel.target_milestone_id)
            .filter(
                MilestoneDependencyModel.source_milestone_id == source_milestone_id
            )
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .all()
        )
        desired = set(targets)

        now = _utcnow()
        to_remove = existing_live - desired
        if to_remove:
            self.db.execute(
                update(MilestoneDependencyModel)
                .where(
                    MilestoneDependencyModel.source_milestone_id == source_milestone_id,
                    MilestoneDependencyModel.target_milestone_id.in_(to_remove),
                    MilestoneDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )

        to_add = desired - existing_live
        for tid in to_add:
            self.db.add(
                MilestoneDependencyModel(
                    source_milestone_id=source_milestone_id,
                    target_milestone_id=tid,
                    project_id=project_id,
                )
            )
        self.db.flush()

    def existing_target_milestone_ids(
        self, project_id: str, ids: Iterable[str]
    ) -> Set[str]:
        """Subset of ``ids`` that exist as live milestones in ``project_id``."""
        ids = list({i for i in ids if i})
        if not ids:
            return set()
        rows = (
            self.db.query(MilestoneModel.id)
            .filter(MilestoneModel.id.in_(ids))
            .filter(MilestoneModel.project_id == project_id)
            .filter(MilestoneModel.deleted_at.is_(None))
            .all()
        )
        return {r[0] for r in rows}

    def would_create_cycle_milestone(
        self, source_milestone_id: str, new_target_ids: Sequence[str],
    ) -> Optional[str]:
        """If adding any of ``new_target_ids`` as a dependency of ``source``
        would create a cycle in the LIVE edge set, return the offending
        target id. Else None.
        """
        all_edges = (
            self.db.query(
                MilestoneDependencyModel.source_milestone_id,
                MilestoneDependencyModel.target_milestone_id,
            )
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .all()
        )
        adj: dict = {}
        for s, t in all_edges:
            adj.setdefault(s, set()).add(t)

        for cand in new_target_ids:
            if cand == source_milestone_id:
                return cand
            stack = deque([cand])
            seen = {cand}
            while stack:
                node = stack.pop()
                if node == source_milestone_id:
                    return cand
                for nxt in adj.get(node, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        return None

    def cascade_remove_milestone_targets(
        self, target_milestone_id: str, *, actor_id: Optional[str] = None,
    ) -> None:
        """Soft-delete every live edge pointing at or leaving this milestone.
        Does NOT commit."""
        now = _utcnow()
        self.db.execute(
            update(MilestoneDependencyModel)
            .where(
                MilestoneDependencyModel.target_milestone_id == target_milestone_id,
                MilestoneDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.execute(
            update(MilestoneDependencyModel)
            .where(
                MilestoneDependencyModel.source_milestone_id == target_milestone_id,
                MilestoneDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.flush()

    def list_milestone_edges_for_source_set(
        self, source_milestone_ids: Sequence[str],
    ) -> List[Tuple[str, str]]:
        """Live (source, target) pairs where source is in the given set."""
        if not source_milestone_ids:
            return []
        rows = (
            self.db.query(
                MilestoneDependencyModel.source_milestone_id,
                MilestoneDependencyModel.target_milestone_id,
            )
            .filter(
                MilestoneDependencyModel.source_milestone_id.in_(source_milestone_ids)
            )
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .all()
        )
        return [(r[0], r[1]) for r in rows]

    # -------------------------------------------------------------------
    # Activity dependencies
    # -------------------------------------------------------------------

    def list_activity_dependencies(self, source_activity_id: str) -> List[str]:
        """Target ids this source depends on (live edges only), sorted."""
        rows = (
            self.db.query(ActivityDependencyModel.target_activity_id)
            .filter(ActivityDependencyModel.source_activity_id == source_activity_id)
            .filter(ActivityDependencyModel.deleted_at.is_(None))
            .all()
        )
        return sorted(r[0] for r in rows)

    def set_activity_dependencies(
        self,
        source_activity_id: str,
        project_id: str,
        target_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        """Replace the source's LIVE dependency target list.

        Targets missing from the new list are soft-deleted. Targets new to
        the list get fresh rows. Does NOT commit.
        """
        targets = list(dict.fromkeys(target_ids))  # de-dup, preserve order

        existing_live = set(
            r[0]
            for r in self.db.query(ActivityDependencyModel.target_activity_id)
            .filter(ActivityDependencyModel.source_activity_id == source_activity_id)
            .filter(ActivityDependencyModel.deleted_at.is_(None))
            .all()
        )
        desired = set(targets)

        now = _utcnow()
        to_remove = existing_live - desired
        if to_remove:
            self.db.execute(
                update(ActivityDependencyModel)
                .where(
                    ActivityDependencyModel.source_activity_id == source_activity_id,
                    ActivityDependencyModel.target_activity_id.in_(to_remove),
                    ActivityDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )

        to_add = desired - existing_live
        for tid in to_add:
            self.db.add(
                ActivityDependencyModel(
                    source_activity_id=source_activity_id,
                    target_activity_id=tid,
                    project_id=project_id,
                )
            )
        self.db.flush()

    def existing_target_activity_ids(
        self, project_id: str, ids: Iterable[str]
    ) -> Set[str]:
        """Subset of ``ids`` that exist as live activities in ``project_id``."""
        ids = list({i for i in ids if i})
        if not ids:
            return set()
        rows = (
            self.db.query(ActivityModel.id)
            .filter(ActivityModel.id.in_(ids))
            .filter(ActivityModel.project_id == project_id)
            .filter(ActivityModel.deleted_at.is_(None))
            .all()
        )
        return {r[0] for r in rows}

    def would_create_cycle_activity(
        self, source_activity_id: str, new_target_ids: Sequence[str],
    ) -> Optional[str]:
        """If adding any of ``new_target_ids`` as a dependency of ``source``
        would create a cycle in the LIVE edge set, return the offending
        target id. Else None.
        """
        all_edges = (
            self.db.query(
                ActivityDependencyModel.source_activity_id,
                ActivityDependencyModel.target_activity_id,
            )
            .filter(ActivityDependencyModel.deleted_at.is_(None))
            .all()
        )
        adj: dict = {}
        for s, t in all_edges:
            adj.setdefault(s, set()).add(t)

        for cand in new_target_ids:
            if cand == source_activity_id:
                return cand  # self-edge is a 1-cycle
            stack = deque([cand])
            seen = {cand}
            while stack:
                node = stack.pop()
                if node == source_activity_id:
                    return cand
                for nxt in adj.get(node, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        return None

    def cascade_remove_activity_targets(
        self, target_activity_id: str, *, actor_id: Optional[str] = None,
    ) -> None:
        """Soft-delete every live dep edge pointing at or leaving this
        activity. Does NOT commit."""
        now = _utcnow()
        # Incoming.
        self.db.execute(
            update(ActivityDependencyModel)
            .where(
                ActivityDependencyModel.target_activity_id == target_activity_id,
                ActivityDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        # Outgoing (this activity is being deleted; its outgoing deps no
        # longer make sense).
        self.db.execute(
            update(ActivityDependencyModel)
            .where(
                ActivityDependencyModel.source_activity_id == target_activity_id,
                ActivityDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.flush()

    # -------------------------------------------------------------------
    # Task dependencies
    # -------------------------------------------------------------------

    def list_task_dependencies(self, source_task_id: str) -> List[str]:
        rows = (
            self.db.query(TaskDependencyModel.target_task_id)
            .filter(TaskDependencyModel.source_task_id == source_task_id)
            .filter(TaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        return sorted(r[0] for r in rows)

    def set_task_dependencies(
        self,
        source_task_id: str,
        project_id: str,
        target_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        targets = list(dict.fromkeys(target_ids))
        existing_live = set(
            r[0]
            for r in self.db.query(TaskDependencyModel.target_task_id)
            .filter(TaskDependencyModel.source_task_id == source_task_id)
            .filter(TaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        desired = set(targets)

        now = _utcnow()
        to_remove = existing_live - desired
        if to_remove:
            self.db.execute(
                update(TaskDependencyModel)
                .where(
                    TaskDependencyModel.source_task_id == source_task_id,
                    TaskDependencyModel.target_task_id.in_(to_remove),
                    TaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )

        to_add = desired - existing_live
        for tid in to_add:
            self.db.add(
                TaskDependencyModel(
                    source_task_id=source_task_id,
                    target_task_id=tid,
                    project_id=project_id,
                )
            )
        self.db.flush()

    def existing_target_tasks(
        self, project_id: str, ids: Iterable[str]
    ) -> List[Tuple[str, str]]:
        """[(task_id, activity_id), ...] for live tasks in ``project_id``."""
        ids = list({i for i in ids if i})
        if not ids:
            return []
        rows = (
            self.db.query(TaskModel.id, TaskModel.activity_id)
            .filter(TaskModel.id.in_(ids))
            .filter(TaskModel.project_id == project_id)
            .filter(TaskModel.deleted_at.is_(None))
            .all()
        )
        return [(r[0], r[1]) for r in rows]

    def activity_pair_is_dependent(
        self, source_activity_id: str, target_activity_id: str
    ) -> bool:
        """True iff a LIVE activity_dependencies row exists for
        (source → target). Same-activity is always True (tasks under the
        same activity may reference each other without an activity edge)."""
        if source_activity_id == target_activity_id:
            return True
        return (
            self.db.query(ActivityDependencyModel.id)
            .filter(
                ActivityDependencyModel.source_activity_id == source_activity_id,
                ActivityDependencyModel.target_activity_id == target_activity_id,
                ActivityDependencyModel.deleted_at.is_(None),
            )
            .first()
            is not None
        )

    def would_create_cycle_task(
        self, source_task_id: str, new_target_ids: Sequence[str],
    ) -> Optional[str]:
        all_edges = (
            self.db.query(
                TaskDependencyModel.source_task_id,
                TaskDependencyModel.target_task_id,
            )
            .filter(TaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        adj: dict = {}
        for s, t in all_edges:
            adj.setdefault(s, set()).add(t)

        for cand in new_target_ids:
            if cand == source_task_id:
                return cand
            stack = deque([cand])
            seen = {cand}
            while stack:
                node = stack.pop()
                if node == source_task_id:
                    return cand
                for nxt in adj.get(node, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        return None

    def cascade_remove_task_targets(
        self, target_task_id: str, *, actor_id: Optional[str] = None,
    ) -> None:
        now = _utcnow()
        self.db.execute(
            update(TaskDependencyModel)
            .where(
                TaskDependencyModel.target_task_id == target_task_id,
                TaskDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.execute(
            update(TaskDependencyModel)
            .where(
                TaskDependencyModel.source_task_id == target_task_id,
                TaskDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.flush()

    # -------------------------------------------------------------------
    # Subtask dependencies
    # -------------------------------------------------------------------

    def list_subtask_dependencies(self, source_subtask_id: str) -> List[str]:
        rows = (
            self.db.query(SubtaskDependencyModel.target_subtask_id)
            .filter(SubtaskDependencyModel.source_subtask_id == source_subtask_id)
            .filter(SubtaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        return sorted(r[0] for r in rows)

    def set_subtask_dependencies(
        self,
        source_subtask_id: str,
        project_id: str,
        target_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        targets = list(dict.fromkeys(target_ids))
        existing_live = set(
            r[0]
            for r in self.db.query(SubtaskDependencyModel.target_subtask_id)
            .filter(SubtaskDependencyModel.source_subtask_id == source_subtask_id)
            .filter(SubtaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        desired = set(targets)

        now = _utcnow()
        to_remove = existing_live - desired
        if to_remove:
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.source_subtask_id == source_subtask_id,
                    SubtaskDependencyModel.target_subtask_id.in_(to_remove),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )

        to_add = desired - existing_live
        for tid in to_add:
            self.db.add(
                SubtaskDependencyModel(
                    source_subtask_id=source_subtask_id,
                    target_subtask_id=tid,
                    project_id=project_id,
                )
            )
        self.db.flush()

    def existing_target_subtasks(
        self, project_id: str, ids: Iterable[str]
    ) -> List[Tuple[str, str]]:
        """[(subtask_id, task_id), ...] for live subtasks in ``project_id``."""
        ids = list({i for i in ids if i})
        if not ids:
            return []
        rows = (
            self.db.query(SubtaskModel.id, SubtaskModel.task_id)
            .filter(SubtaskModel.id.in_(ids))
            .filter(SubtaskModel.project_id == project_id)
            .filter(SubtaskModel.deleted_at.is_(None))
            .all()
        )
        return [(r[0], r[1]) for r in rows]

    def task_pair_is_dependent(
        self, source_task_id: str, target_task_id: str
    ) -> bool:
        if source_task_id == target_task_id:
            return True
        return (
            self.db.query(TaskDependencyModel.id)
            .filter(
                TaskDependencyModel.source_task_id == source_task_id,
                TaskDependencyModel.target_task_id == target_task_id,
                TaskDependencyModel.deleted_at.is_(None),
            )
            .first()
            is not None
        )

    def would_create_cycle_subtask(
        self, source_subtask_id: str, new_target_ids: Sequence[str],
    ) -> Optional[str]:
        all_edges = (
            self.db.query(
                SubtaskDependencyModel.source_subtask_id,
                SubtaskDependencyModel.target_subtask_id,
            )
            .filter(SubtaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        adj: dict = {}
        for s, t in all_edges:
            adj.setdefault(s, set()).add(t)

        for cand in new_target_ids:
            if cand == source_subtask_id:
                return cand
            stack = deque([cand])
            seen = {cand}
            while stack:
                node = stack.pop()
                if node == source_subtask_id:
                    return cand
                for nxt in adj.get(node, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
        return None

    def cascade_remove_subtask_targets(
        self, target_subtask_id: str, *, actor_id: Optional[str] = None,
    ) -> None:
        now = _utcnow()
        self.db.execute(
            update(SubtaskDependencyModel)
            .where(
                SubtaskDependencyModel.target_subtask_id == target_subtask_id,
                SubtaskDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.execute(
            update(SubtaskDependencyModel)
            .where(
                SubtaskDependencyModel.source_subtask_id == target_subtask_id,
                SubtaskDependencyModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, deleted_by=actor_id)
        )
        self.db.flush()

    # -------------------------------------------------------------------
    # Bulk cascade on activity / task / milestone soft-delete
    # -------------------------------------------------------------------

    def cascade_remove_for_deleted_activity_subtree(
        self,
        activity_id: str,
        task_ids: Sequence[str],
        subtask_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        """Soft-delete every dep edge (incoming + outgoing) that touches
        ``activity_id`` and every task / subtask in its cascaded subtree.
        Called post-soft-delete of the rows themselves.
        """
        now = _utcnow()
        # Activity edges.
        self.cascade_remove_activity_targets(activity_id, actor_id=actor_id)

        # Task edges.
        if task_ids:
            tids = list(task_ids)
            self.db.execute(
                update(TaskDependencyModel)
                .where(
                    TaskDependencyModel.target_task_id.in_(tids),
                    TaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(TaskDependencyModel)
                .where(
                    TaskDependencyModel.source_task_id.in_(tids),
                    TaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )

        # Subtask edges.
        if subtask_ids:
            sids = list(subtask_ids)
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.target_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.source_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
        self.db.flush()

    def cascade_remove_for_deleted_task_subtree(
        self,
        task_id: str,
        subtask_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        """Soft-delete edges for a task and its cascaded subtasks."""
        now = _utcnow()
        self.cascade_remove_task_targets(task_id, actor_id=actor_id)
        if subtask_ids:
            sids = list(subtask_ids)
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.target_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.source_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
        self.db.flush()

    def cascade_remove_for_deleted_milestone_subtree(
        self,
        activity_ids: Sequence[str],
        task_ids: Sequence[str],
        subtask_ids: Sequence[str],
        *,
        actor_id: Optional[str] = None,
    ) -> None:
        """Soft-delete every dep edge across a milestone's A/T/S subtree.

        Caller passes in pre-computed live-row id lists (collected BEFORE
        soft-deleting the rows themselves). One transaction, one flush.
        """
        now = _utcnow()
        if activity_ids:
            aids = list(activity_ids)
            self.db.execute(
                update(ActivityDependencyModel)
                .where(
                    ActivityDependencyModel.target_activity_id.in_(aids),
                    ActivityDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(ActivityDependencyModel)
                .where(
                    ActivityDependencyModel.source_activity_id.in_(aids),
                    ActivityDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
        if task_ids:
            tids = list(task_ids)
            self.db.execute(
                update(TaskDependencyModel)
                .where(
                    TaskDependencyModel.target_task_id.in_(tids),
                    TaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(TaskDependencyModel)
                .where(
                    TaskDependencyModel.source_task_id.in_(tids),
                    TaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
        if subtask_ids:
            sids = list(subtask_ids)
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.target_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
            self.db.execute(
                update(SubtaskDependencyModel)
                .where(
                    SubtaskDependencyModel.source_subtask_id.in_(sids),
                    SubtaskDependencyModel.deleted_at.is_(None),
                )
                .values(deleted_at=now, deleted_by=actor_id)
            )
        self.db.flush()

    # -------------------------------------------------------------------
    # Version cloning
    # -------------------------------------------------------------------

    def clone_milestone_dependencies_for_version(
        self,
        source_project_id: str,
        target_project_id: str,
        milestone_id_map: dict,
    ) -> int:
        """Copy LIVE milestone_dependencies from baseline into a new version,
        rewriting source/target ids via ``milestone_id_map``. Soft-deleted
        edges are NOT carried forward.

        Returns the number of edges inserted. Does NOT commit.
        """
        if not milestone_id_map:
            return 0

        src_edges = (
            self.db.query(
                MilestoneDependencyModel.source_milestone_id,
                MilestoneDependencyModel.target_milestone_id,
            )
            .filter(MilestoneDependencyModel.project_id == source_project_id)
            .filter(MilestoneDependencyModel.deleted_at.is_(None))
            .all()
        )
        inserted = 0
        for src, tgt in src_edges:
            new_src = milestone_id_map.get(src)
            new_tgt = milestone_id_map.get(tgt)
            if new_src is None or new_tgt is None:
                continue
            self.db.add(
                MilestoneDependencyModel(
                    source_milestone_id=new_src,
                    target_milestone_id=new_tgt,
                    project_id=target_project_id,
                )
            )
            inserted += 1
        if inserted:
            self.db.flush()
        return inserted

    def clone_activity_dependencies_for_version(
        self,
        source_project_id: str,
        target_project_id: str,
        activity_id_map: dict,
    ) -> int:
        """Copy LIVE activity_dependencies from baseline into a new version,
        rewriting source/target ids via ``activity_id_map``. Soft-deleted
        edges are NOT carried forward.

        Returns the number of edges inserted. Does NOT commit.
        """
        if not activity_id_map:
            return 0

        src_edges = (
            self.db.query(
                ActivityDependencyModel.source_activity_id,
                ActivityDependencyModel.target_activity_id,
            )
            .filter(ActivityDependencyModel.project_id == source_project_id)
            .filter(ActivityDependencyModel.deleted_at.is_(None))
            .all()
        )
        inserted = 0
        for src, tgt in src_edges:
            new_src = activity_id_map.get(src)
            new_tgt = activity_id_map.get(tgt)
            if new_src is None or new_tgt is None:
                continue
            self.db.add(
                ActivityDependencyModel(
                    source_activity_id=new_src,
                    target_activity_id=new_tgt,
                    project_id=target_project_id,
                )
            )
            inserted += 1
        if inserted:
            self.db.flush()
        return inserted
