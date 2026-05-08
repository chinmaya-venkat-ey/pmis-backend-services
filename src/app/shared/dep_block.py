"""External-dependency block on M/A/T/S delete (doc 34, 2/3).

Before soft-deleting an M/A/T/S, refuse the operation if anything in
the about-to-be-deleted subtree is the TARGET of a live dependency
edge whose SOURCE lives outside the subtree.

Rationale: a cascade-delete that takes a dep target with it leaves the
source pointing at a now-deleted entity. The existing cascade does
soft-delete the dep edges automatically, but doing so silently breaks
the user's expressed plan ("X depends on Y"). Refusing the delete and
naming the offending source-target pair lets the user choose: remove
the dep first, or change their mind about the delete.

Self-contained deps don't block — if M2 → M1 and we're deleting their
shared parent project, both are in the subtree and the cascade is
internally consistent.

Helper API:

    collect_external_dep_blockers(
        db, *, root_kind, root_id, project_id,
    ) -> List[Blocker]

    raise_if_external_blockers(blockers, *, root_label, root_kind)

The raise helper builds a ``ValidationError`` with the structured
``_embedded.details.blockers`` list every wired delete service
expects.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import ValidationError
from ..infrastructure.db.models.activity import ActivityModel
from ..infrastructure.db.models.activity_dependency import (
    ActivityDependencyModel,
)
from ..infrastructure.db.models.milestone import MilestoneModel
from ..infrastructure.db.models.milestone_dependency import (
    MilestoneDependencyModel,
)
from ..infrastructure.db.models.subtask import SubtaskModel
from ..infrastructure.db.models.subtask_dependency import (
    SubtaskDependencyModel,
)
from ..infrastructure.db.models.task import TaskModel
from ..infrastructure.db.models.task_dependency import TaskDependencyModel
from .labels import build_label_index_for_project


# Kind constants — match the strings used by the labels + comments
# layers throughout the codebase.
KIND_MILESTONE = "milestone"
KIND_ACTIVITY = "activity"
KIND_TASK = "task"
KIND_SUBTASK = "subtask"


@dataclass
class Blocker:
    """One entry in a dep-block error response.

    ``source`` is the user-facing label of the dependent (e.g. ``M2``,
    ``A1.3``, ``T1.2.4`` or its ``name`` fallback when no label fits).
    ``target`` is the entity inside the delete subtree that the source
    depends on. The kinds always match for any single edge (milestone
    deps reference milestones, activity deps reference activities, etc.)
    but we surface both kinds so the FE can render mixed-kind groups
    when several blockers stack up.
    """
    source: str
    source_kind: str
    target: str
    target_kind: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "source": self.source,
            "sourceKind": self.source_kind,
            "target": self.target,
            "targetKind": self.target_kind,
        }


# ---------------------------------------------------------------------------
# Subtree id collection — walks down from the root to the leaves.
# ---------------------------------------------------------------------------


def _milestone_subtree_ids(
    db: Session, milestone_id: str,
) -> Dict[str, List[str]]:
    a_ids = [
        r[0] for r in db.execute(
            select(ActivityModel.id).where(
                ActivityModel.milestone_id == milestone_id,
                ActivityModel.deleted_at.is_(None),
            )
        ).all()
    ]
    t_ids = []
    if a_ids:
        t_ids = [
            r[0] for r in db.execute(
                select(TaskModel.id).where(
                    TaskModel.activity_id.in_(a_ids),
                    TaskModel.deleted_at.is_(None),
                )
            ).all()
        ]
    s_ids = _all_descendant_subtask_ids(db, parent_task_ids=t_ids)
    return {
        KIND_MILESTONE: [milestone_id],
        KIND_ACTIVITY: a_ids,
        KIND_TASK: t_ids,
        KIND_SUBTASK: s_ids,
    }


def _activity_subtree_ids(
    db: Session, activity_id: str,
) -> Dict[str, List[str]]:
    t_ids = [
        r[0] for r in db.execute(
            select(TaskModel.id).where(
                TaskModel.activity_id == activity_id,
                TaskModel.deleted_at.is_(None),
            )
        ).all()
    ]
    s_ids = _all_descendant_subtask_ids(db, parent_task_ids=t_ids)
    return {
        KIND_MILESTONE: [],
        KIND_ACTIVITY: [activity_id],
        KIND_TASK: t_ids,
        KIND_SUBTASK: s_ids,
    }


def _task_subtree_ids(
    db: Session, task_id: str,
) -> Dict[str, List[str]]:
    s_ids = _all_descendant_subtask_ids(db, parent_task_ids=[task_id])
    return {
        KIND_MILESTONE: [],
        KIND_ACTIVITY: [],
        KIND_TASK: [task_id],
        KIND_SUBTASK: s_ids,
    }


def _subtask_subtree_ids(
    db: Session, subtask_id: str,
) -> Dict[str, List[str]]:
    """The subtask itself + every nested descendant subtask. Tasks +
    activities + milestones can never be inside a subtask subtree."""
    descendant_ids = [subtask_id]
    queue = deque([subtask_id])
    while queue:
        parent = queue.popleft()
        children = [
            r[0] for r in db.execute(
                select(SubtaskModel.id).where(
                    SubtaskModel.parent_subtask_id == parent,
                    SubtaskModel.deleted_at.is_(None),
                )
            ).all()
        ]
        descendant_ids.extend(children)
        queue.extend(children)
    return {
        KIND_MILESTONE: [],
        KIND_ACTIVITY: [],
        KIND_TASK: [],
        KIND_SUBTASK: descendant_ids,
    }


def _all_descendant_subtask_ids(
    db: Session, *, parent_task_ids: List[str],
) -> List[str]:
    """Top-level subtasks under the given tasks PLUS every nested
    descendant. BFS so we don't blow the stack on deep nesting.
    Soft-deleted rows are skipped at every level."""
    if not parent_task_ids:
        return []

    # Top-level subtasks: parent_subtask_id IS NULL, task_id IN parents.
    queue = deque(
        r[0] for r in db.execute(
            select(SubtaskModel.id).where(
                SubtaskModel.task_id.in_(parent_task_ids),
                SubtaskModel.parent_subtask_id.is_(None),
                SubtaskModel.deleted_at.is_(None),
            )
        ).all()
    )
    out: List[str] = list(queue)
    while queue:
        parent = queue.popleft()
        children = [
            r[0] for r in db.execute(
                select(SubtaskModel.id).where(
                    SubtaskModel.parent_subtask_id == parent,
                    SubtaskModel.deleted_at.is_(None),
                )
            ).all()
        ]
        out.extend(children)
        queue.extend(children)
    return out


_SUBTREE_FN = {
    KIND_MILESTONE: _milestone_subtree_ids,
    KIND_ACTIVITY: _activity_subtree_ids,
    KIND_TASK: _task_subtree_ids,
    KIND_SUBTASK: _subtask_subtree_ids,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def collect_external_dep_blockers(
    db: Session,
    *,
    root_kind: str,
    root_id: str,
    project_id: str,
) -> List[Blocker]:
    """Return every live dep edge whose target is in the
    ``(root_kind, root_id)`` subtree but whose source lives outside it.

    Only LIVE edges are considered (``deleted_at IS NULL``); soft-deleted
    ones don't block.

    Self-contained edges (source AND target both in the subtree) do not
    block — the cascade soft-deletes them along with the rest of the
    subtree consistently.

    Source labels are resolved against ``project_id`` so the message
    renders the user-facing display code (``M2``, ``A1.3``, …). Names
    fall back when no label is available.
    """
    if root_kind not in _SUBTREE_FN:
        raise ValueError(f"Unknown root_kind: {root_kind!r}")

    subtree = _SUBTREE_FN[root_kind](db, root_id)
    label_index = build_label_index_for_project(db, project_id)

    blockers: List[Blocker] = []

    # Milestone edges: dep where target_milestone_id in M_ids, source NOT in M_ids
    if subtree[KIND_MILESTONE]:
        m_ids = subtree[KIND_MILESTONE]
        rows = db.execute(
            select(
                MilestoneDependencyModel.source_milestone_id,
                MilestoneDependencyModel.target_milestone_id,
            ).where(
                MilestoneDependencyModel.target_milestone_id.in_(m_ids),
                MilestoneDependencyModel.source_milestone_id.notin_(m_ids),
                MilestoneDependencyModel.deleted_at.is_(None),
            )
        ).all()
        for src_id, tgt_id in rows:
            blockers.append(Blocker(
                source=label_index.label_of(KIND_MILESTONE, src_id) or src_id,
                source_kind=KIND_MILESTONE,
                target=label_index.label_of(KIND_MILESTONE, tgt_id) or tgt_id,
                target_kind=KIND_MILESTONE,
            ))

    if subtree[KIND_ACTIVITY]:
        a_ids = subtree[KIND_ACTIVITY]
        rows = db.execute(
            select(
                ActivityDependencyModel.source_activity_id,
                ActivityDependencyModel.target_activity_id,
            ).where(
                ActivityDependencyModel.target_activity_id.in_(a_ids),
                ActivityDependencyModel.source_activity_id.notin_(a_ids),
                ActivityDependencyModel.deleted_at.is_(None),
            )
        ).all()
        for src_id, tgt_id in rows:
            blockers.append(Blocker(
                source=label_index.label_of(KIND_ACTIVITY, src_id) or src_id,
                source_kind=KIND_ACTIVITY,
                target=label_index.label_of(KIND_ACTIVITY, tgt_id) or tgt_id,
                target_kind=KIND_ACTIVITY,
            ))

    if subtree[KIND_TASK]:
        t_ids = subtree[KIND_TASK]
        rows = db.execute(
            select(
                TaskDependencyModel.source_task_id,
                TaskDependencyModel.target_task_id,
            ).where(
                TaskDependencyModel.target_task_id.in_(t_ids),
                TaskDependencyModel.source_task_id.notin_(t_ids),
                TaskDependencyModel.deleted_at.is_(None),
            )
        ).all()
        for src_id, tgt_id in rows:
            blockers.append(Blocker(
                source=label_index.label_of(KIND_TASK, src_id) or src_id,
                source_kind=KIND_TASK,
                target=label_index.label_of(KIND_TASK, tgt_id) or tgt_id,
                target_kind=KIND_TASK,
            ))

    if subtree[KIND_SUBTASK]:
        s_ids = subtree[KIND_SUBTASK]
        rows = db.execute(
            select(
                SubtaskDependencyModel.source_subtask_id,
                SubtaskDependencyModel.target_subtask_id,
            ).where(
                SubtaskDependencyModel.target_subtask_id.in_(s_ids),
                SubtaskDependencyModel.source_subtask_id.notin_(s_ids),
                SubtaskDependencyModel.deleted_at.is_(None),
            )
        ).all()
        for src_id, tgt_id in rows:
            blockers.append(Blocker(
                source=label_index.label_of(KIND_SUBTASK, src_id) or src_id,
                source_kind=KIND_SUBTASK,
                target=label_index.label_of(KIND_SUBTASK, tgt_id) or tgt_id,
                target_kind=KIND_SUBTASK,
            ))

    return blockers


def raise_if_external_blockers(
    blockers: List[Blocker],
    *,
    root_label: str,
    root_kind: str,
) -> None:
    """Translate a non-empty blocker list into a 422 ValidationError.

    No-op when ``blockers`` is empty (the caller can call this
    unconditionally without checking length).

    Error shape (after ``DomainError`` projection):

      {
        "error": {
          "errorIdentifier": "dependency_block",
          "message": "Cannot delete <root>: ...",
          "_embedded": {
            "details": {
              "errorIdentifier": "dependency_block",
              "rootKind": "milestone",
              "rootLabel": "M1 — Foundation",
              "blockers": [
                {"source": "M2", "sourceKind": "milestone",
                 "target": "M1", "targetKind": "milestone"},
                ...
              ]
            }
          }
        },
        "status": 422
      }
    """
    if not blockers:
        return

    # Compose a human-readable summary listing up to a few blockers.
    summary_lines = [
        f"{b.source} (depends on {b.target})" for b in blockers
    ]
    summary = "; ".join(summary_lines)

    raise ValidationError(
        f"Cannot delete {root_kind} '{root_label}' — the following live "
        f"dependencies must be removed first: {summary}.",
        details={
            "errorIdentifier": "dependency_block",
            "rootKind": root_kind,
            "rootLabel": root_label,
            "blockers": [b.to_dict() for b in blockers],
        },
    )
