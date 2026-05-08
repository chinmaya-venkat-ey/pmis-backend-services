"""Fetch a single task (+ optional resource)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.tasks.task import Task
from .....domain.tasks.task_resource import TaskResource
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.task_repository import TaskRepository


def get_task(db: Session, task_id: str, include_deleted: bool = False) -> Task:
    t = TaskRepository(db).get_by_id(task_id, include_deleted=include_deleted)
    if t is None:
        raise NotFoundError("The task could not be found.")
    t.depends_on = DependencyRepository(db).list_task_dependencies(task_id)
    return t


def get_task_with_resource(
    db: Session, task_id: str, include_deleted: bool = False,
) -> Tuple[Task, Optional[TaskResource]]:
    repo = TaskRepository(db)
    t = repo.get_by_id(task_id, include_deleted=include_deleted)
    if t is None:
        raise NotFoundError("The task could not be found.")
    res = repo.get_live_resource(task_id) if t.type == "resource" else None
    t.depends_on = DependencyRepository(db).list_task_dependencies(task_id)
    return t, res
