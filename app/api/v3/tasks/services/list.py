"""List tasks under an activity."""
from dataclasses import dataclass
from typing import List
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.tasks.task import Task
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.task_dependency import TaskDependencyModel
from .....infrastructure.db.repositories.task_repository import TaskRepository


@dataclass
class PagedTasks:
    items: List[Task]
    total: int
    page: int
    page_size: int


def list_tasks(
    db: Session, *, activity_id: str, page: int, page_size: int, include_deleted: bool,
) -> PagedTasks:
    a = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == activity_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .first()
    )
    if a is None:
        raise NotFoundError("The activity could not be found.")
    offset = max(page - 1, 0) * page_size
    items, total = TaskRepository(db).list_by_activity(
        activity_id=activity_id, offset=offset, limit=page_size,
        include_deleted=include_deleted,
    )
    # Bulk-load dependency lists for the page in one query.
    if items:
        ids = [t.id for t in items]
        rows = (
            db.query(
                TaskDependencyModel.source_task_id,
                TaskDependencyModel.target_task_id,
            )
            .filter(TaskDependencyModel.source_task_id.in_(ids))
            .filter(TaskDependencyModel.deleted_at.is_(None))
            .all()
        )
        bucket: dict = {}
        for src, tgt in rows:
            bucket.setdefault(src, []).append(tgt)
        for t in items:
            t.depends_on = sorted(bucket.get(t.id, []))
    return PagedTasks(items=items, total=total, page=page, page_size=page_size)
