"""Soft-delete an activity (cascades to tasks/subtasks + all resources +
all dependency edges in the subtree)."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....core.project_lock import assert_milestone_activity_writable
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.activity_repository import ActivityRepository
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from ...projects.services.audit import record_audit
from ...projects.services.baseline_version_sync import (
    ACTION_ACTIVITY_DELETE,
    propagate_activity_soft_delete,
)


def delete_activity(db: Session, *, activity_id: str, current_user_id: Optional[int]) -> None:
    repo = ActivityRepository(db)
    model = repo.get_model(activity_id)
    if model is None:
        raise NotFoundError("The activity could not be found.")
    assert_milestone_activity_writable(db, model.project_id)

    # Snapshot the subtree id sets BEFORE we soft-delete, so the
    # dependency-cascade query can use them. (After soft-delete, deleted_at
    # filters would exclude these ids from the standard repository queries.)
    task_ids = [
        r[0]
        for r in db.execute(
            select(TaskModel.id)
            .where(TaskModel.activity_id == activity_id)
            .where(TaskModel.deleted_at.is_(None))
        ).all()
    ]
    subtask_ids: list = []
    if task_ids:
        subtask_ids = [
            r[0]
            for r in db.execute(
                select(SubtaskModel.id)
                .where(SubtaskModel.task_id.in_(task_ids))
                .where(SubtaskModel.deleted_at.is_(None))
            ).all()
        ]

    before = {
        "activity_id": activity_id,
        "name": model.name,
        "milestone_id": model.milestone_id,
        "project_id": model.project_id,
    }

    # The cascade soft_delete commits internally — we wipe deps first so the
    # dep-cleanup is part of the same logical change. The cascade also
    # commits, which finalizes both writes.
    DependencyRepository(db).cascade_remove_for_deleted_activity_subtree(
        activity_id, task_ids, subtask_ids,
        actor_id=current_user_id,
    )
    repo.soft_delete_with_cascade(activity_id, deleted_by=current_user_id)
    record_audit(
        db,
        project_id=model.project_id,
        actor_id=current_user_id,
        action=ACTION_ACTIVITY_DELETE,
        before=before,
        after=None,
    )
    db.commit()
    propagate_activity_soft_delete(
        db, baseline_activity_id=activity_id, actor_id=current_user_id,
    )
