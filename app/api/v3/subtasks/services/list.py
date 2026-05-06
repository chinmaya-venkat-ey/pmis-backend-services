"""List subtasks under a task.

Doc 28: ``items`` is the paginated set of TOP-LEVEL subtasks
(parent_subtask_id IS NULL). ``nested`` is every other subtask under
the same task — flat — for the controller to group + embed
recursively into each top-level row's ``subtasks: [...]`` array.
``total`` reflects only top-level subtasks (correct semantics for
pagination — each "page" is a slice of top-level rows; their entire
subtrees come along).
"""
from dataclasses import dataclass, field
from typing import List
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.subtasks.subtask import Subtask
from .....infrastructure.db.models.subtask_dependency import SubtaskDependencyModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository


@dataclass
class PagedSubtasks:
    items: List[Subtask]                    # paginated top-level subtasks
    total: int                              # count of top-level subtasks (for pagination)
    page: int
    page_size: int
    # Doc 28: every nested subtask under the task, flat. Controller
    # builds an adjacency map keyed on ``parent_subtask_id`` and embeds
    # children recursively per top-level row.
    nested: List[Subtask] = field(default_factory=list)


def list_subtasks(
    db: Session, *, task_id: str, page: int, page_size: int, include_deleted: bool,
) -> PagedSubtasks:
    t = (
        db.query(TaskModel)
        .filter(TaskModel.id == task_id)
        .filter(TaskModel.deleted_at.is_(None))
        .first()
    )
    if t is None:
        raise NotFoundError("The task could not be found.")
    offset = max(page - 1, 0) * page_size
    repo = SubtaskRepository(db)
    items, total = repo.list_by_task(
        task_id=task_id, offset=offset, limit=page_size, include_deleted=include_deleted,
    )
    # Doc 28: load every nested subtask under this task in one query.
    # The controller groups them by parent_subtask_id to embed children
    # recursively in each top-level row's response.
    nested = repo.list_nested_under_task(
        task_id=task_id, include_deleted=include_deleted,
    )

    # Bulk-load dependsOn for ALL subtasks the response will include —
    # the page's top-level rows AND every nested descendant we'll embed.
    # Single query, indexed on source_subtask_id.
    all_ids = [s.id for s in items] + [s.id for s in nested]
    if all_ids:
        rows = (
            db.query(
                SubtaskDependencyModel.source_subtask_id,
                SubtaskDependencyModel.target_subtask_id,
            )
            .filter(SubtaskDependencyModel.source_subtask_id.in_(all_ids))
            .filter(SubtaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        bucket: dict = {}
        for src, tgt in rows:
            bucket.setdefault(src, []).append(tgt)
        for s in items:
            s.depends_on = sorted(bucket.get(s.id, []))
        for s in nested:
            s.depends_on = sorted(bucket.get(s.id, []))
    return PagedSubtasks(
        items=items, total=total, page=page, page_size=page_size, nested=nested,
    )
