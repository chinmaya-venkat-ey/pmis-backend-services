"""Soft-delete a subtask (leaf; wipe resource + dependency edges)."""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository


def delete_subtask(db: Session, *, subtask_id: str, current_user_id: Optional[int]) -> None:
    repo = SubtaskRepository(db)
    model = repo.get_model(subtask_id)
    if model is None:
        raise NotFoundError("The subtask could not be found.")
    assert_task_subtask_writable(db, model.project_id)

    # Soft-delete in-edges pointing at this subtask and out-edges leaving it.
    DependencyRepository(db).cascade_remove_subtask_targets(
        subtask_id, actor_id=current_user_id,
    )
    repo.soft_delete(subtask_id, deleted_by=current_user_id)
