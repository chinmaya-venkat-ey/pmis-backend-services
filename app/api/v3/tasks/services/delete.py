"""Soft-delete a task (cascades to subtasks + resources + dependency edges)."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.task_repository import TaskRepository


def delete_task(db: Session, *, task_id: str, current_user_id: Optional[int]) -> None:
    repo = TaskRepository(db)
    model = repo.get_model(task_id)
    if model is None:
        raise NotFoundError("The task could not be found.")
    assert_task_subtask_writable(db, model.project_id)

    # Snapshot subtree subtask ids before soft-delete.
    subtask_ids = [
        r[0]
        for r in db.execute(
            select(SubtaskModel.id)
            .where(SubtaskModel.task_id == task_id)
            .where(SubtaskModel.deleted_at.is_(None))
        ).all()
    ]

    DependencyRepository(db).cascade_remove_for_deleted_task_subtree(
        task_id, subtask_ids,
        actor_id=current_user_id,
    )
    repo.soft_delete_with_cascade(task_id, deleted_by=current_user_id)
