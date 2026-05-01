"""Soft-delete a milestone (cascades down + wipes dependency edges)."""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....core.project_lock import assert_milestone_activity_writable
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository
from ...projects.services.audit import record_audit
from ...projects.services.baseline_version_sync import (
    ACTION_MILESTONE_DELETE,
    propagate_milestone_soft_delete,
)


def delete_milestone(db: Session, *, milestone_id: str, current_user_id: Optional[int]) -> None:
    repo = MilestoneRepository(db)
    model = repo.get_model(milestone_id)
    if model is None:
        raise NotFoundError("The milestone could not be found.")
    assert_milestone_activity_writable(db, model.project_id)

    # Snapshot the A/T/S subtree for dep-cascade BEFORE soft-delete.
    activity_ids = [
        r[0]
        for r in db.execute(
            select(ActivityModel.id).where(
                ActivityModel.milestone_id == milestone_id,
                ActivityModel.deleted_at.is_(None),
            )
        ).all()
    ]
    task_ids: list = []
    subtask_ids: list = []
    if activity_ids:
        task_ids = [
            r[0]
            for r in db.execute(
                select(TaskModel.id).where(
                    TaskModel.activity_id.in_(activity_ids),
                    TaskModel.deleted_at.is_(None),
                )
            ).all()
        ]
        if task_ids:
            subtask_ids = [
                r[0]
                for r in db.execute(
                    select(SubtaskModel.id).where(
                        SubtaskModel.task_id.in_(task_ids),
                        SubtaskModel.deleted_at.is_(None),
                    )
                ).all()
            ]

    before = {
        "milestone_id": milestone_id,
        "name": model.name,
        "project_id": model.project_id,
    }

    # Soft-delete all dep edges touching the subtree before we soft-delete
    # the rows themselves. Single call — the repo handles the bulk UPDATEs.
    DependencyRepository(db).cascade_remove_for_deleted_milestone_subtree(
        activity_ids, task_ids, subtask_ids,
        actor_id=current_user_id,
    )

    repo.soft_delete_with_cascade(milestone_id, deleted_by=current_user_id)
    record_audit(
        db,
        project_id=model.project_id,
        actor_id=current_user_id,
        action=ACTION_MILESTONE_DELETE,
        before=before,
        after=None,
    )
    db.commit()
    propagate_milestone_soft_delete(
        db, baseline_milestone_id=milestone_id, actor_id=current_user_id,
    )
