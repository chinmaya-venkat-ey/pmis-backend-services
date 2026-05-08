"""Restore a soft-deleted subtask. Parent task must be live."""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_project_editable
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository
from .....domain.subtasks.subtask import Subtask


def restore_subtask(db: Session, *, subtask_id: str, current_user_id: Optional[int]) -> Subtask:
    repo = SubtaskRepository(db)
    model = repo.get_model(subtask_id, include_deleted=True)
    if model is None:
        raise NotFoundError("The subtask could not be found.")
    if model.deleted_at is None:
        raise ValidationError(
            "This subtask is already active and does not need to be restored."
        )
    parent = (
        db.query(TaskModel)
        .filter(TaskModel.id == model.task_id)
        .filter(TaskModel.deleted_at.is_(None))
        .first()
    )
    if parent is None:
        raise ValidationError(
            "The task this subtask belongs to has been deleted. "
            "Please restore the task first."
        )
    assert_project_editable(db, model.project_id)
    restored = repo.restore(subtask_id, restored_by=current_user_id)
    restored.depends_on = []
    return restored
