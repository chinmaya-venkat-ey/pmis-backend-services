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
from .....shared.dep_block import (
    KIND_TASK,
    collect_external_dep_blockers,
    raise_if_external_blockers,
)


def delete_task(db: Session, *, task_id: str, current_user_id: Optional[int]) -> None:
    repo = TaskRepository(db)
    model = repo.get_model(task_id)
    if model is None:
        raise NotFoundError("The task could not be found.")
    assert_task_subtask_writable(db, model.project_id)

    # Doc 34: refuse delete if any external dep targets this subtree.
    blockers = collect_external_dep_blockers(
        db,
        root_kind=KIND_TASK,
        root_id=task_id,
        project_id=model.project_id,
    )
    raise_if_external_blockers(
        blockers, root_label=model.name, root_kind=KIND_TASK,
    )

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

    # Doc 33: subtree audit expansion.
    from ...projects.services.audit import ACTION_TASK_DELETE, record_audit
    record_audit(
        db,
        project_id=model.project_id,
        actor_id=current_user_id,
        action=ACTION_TASK_DELETE,
        before={
            "task_id": task_id,
            "name": model.name,
            "activity_id": model.activity_id,
        },
        after=None,
    )
    db.commit()
