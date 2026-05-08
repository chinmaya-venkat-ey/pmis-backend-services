"""Fetch a single subtask (+ optional resource)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.subtasks.subtask import Subtask
from .....domain.subtasks.subtask_resource import SubtaskResource
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository


def get_subtask(db: Session, subtask_id: str, include_deleted: bool = False) -> Subtask:
    s = SubtaskRepository(db).get_by_id(subtask_id, include_deleted=include_deleted)
    if s is None:
        raise NotFoundError("The subtask could not be found.")
    s.depends_on = DependencyRepository(db).list_subtask_dependencies(subtask_id)
    return s


def get_subtask_with_resource(
    db: Session, subtask_id: str, include_deleted: bool = False,
) -> Tuple[Subtask, Optional[SubtaskResource]]:
    repo = SubtaskRepository(db)
    s = repo.get_by_id(subtask_id, include_deleted=include_deleted)
    if s is None:
        raise NotFoundError("The subtask could not be found.")
    res = repo.get_live_resource(subtask_id) if s.type == "resource" else None
    s.depends_on = DependencyRepository(db).list_subtask_dependencies(subtask_id)
    return s, res
