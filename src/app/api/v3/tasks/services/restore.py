"""Restore a soft-deleted task (admin). Parent activity must be live."""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_project_editable
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.repositories.task_repository import TaskRepository
from .....domain.tasks.task import Task


def restore_task(db: Session, *, task_id: str, current_user_id: Optional[int]) -> Task:
    repo = TaskRepository(db)
    model = repo.get_model(task_id, include_deleted=True)
    if model is None:
        raise NotFoundError("The task could not be found.")
    if model.deleted_at is None:
        raise ValidationError(
            "This task is already active and does not need to be restored."
        )
    parent = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == model.activity_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .first()
    )
    if parent is None:
        raise ValidationError(
            "The activity this task belongs to has been deleted. "
            "Please restore the activity first."
        )
    assert_project_editable(db, model.project_id)
    restored = repo.restore(task_id, restored_by=current_user_id)
    # Deps were purged on delete; a restored task starts with an empty list.
    restored.depends_on = []
    return restored
