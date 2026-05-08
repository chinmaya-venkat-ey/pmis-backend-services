"""
Cascade soft-delete into the M/A/T/S subtree when a project is soft-deleted.

EXPOSED TO THE PROJECTS MODULE. Call this from projects.services.delete
INSIDE the project's own transaction, BEFORE committing.

Because project_id is denormalized onto every one of our tables, we don't
need JOINs. Each UPDATE is one indexed scan per table.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.activity_resource import ActivityResourceModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.models.task_resource import TaskResourceModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.subtask_resource import SubtaskResourceModel
from .....shared.comments_attachments_cascade import (
    cascade_soft_delete_comments_and_attachments,
)


def cascade_soft_delete_project(
    db: Session, project_id: str, deleted_by: Optional[str] = None,
) -> None:
    """
    Stamp deleted_at on every live row under the project, across all seven
    of our tables. One UPDATE per table, keyed on the denormalized project_id.

    Does NOT commit -- the caller controls the transaction boundary so this
    can be wrapped into the project's delete transaction.
    """
    now = datetime.now(timezone.utc)

    # Resource tables first (leaves of FK dependency), then main entities
    # bottom-up. The order doesn't strictly matter for correctness (we're
    # stamping, not hard-deleting) but keeping it consistent with
    # cascade-on-delete semantics helps audit reasoning.
    for table, has_updated_by in (
        (SubtaskResourceModel, False),
        (TaskResourceModel, False),
        (ActivityResourceModel, False),
        (SubtaskModel, True),
        (TaskModel, True),
        (ActivityModel, True),
        (MilestoneModel, True),
    ):
        values = {"deleted_at": now, "updated_at": now}
        if has_updated_by:
            values["updated_by"] = deleted_by
        db.execute(
            update(table)
            .where(table.project_id == project_id, table.deleted_at.is_(None))
            .values(**values)
        )

    # Doc 34: cascade comments + attachments under every M/A/T/S we
    # just soft-deleted. The four entity tables all carry the
    # denormalized ``project_id`` column so we can find the just-stamped
    # rows in one indexed scan per kind.
    cascade_soft_delete_comments_and_attachments(
        db,
        targets=[
            ("milestone", select(MilestoneModel.id).where(
                MilestoneModel.project_id == project_id,
                MilestoneModel.deleted_at == now,
            )),
            ("activity", select(ActivityModel.id).where(
                ActivityModel.project_id == project_id,
                ActivityModel.deleted_at == now,
            )),
            ("task", select(TaskModel.id).where(
                TaskModel.project_id == project_id,
                TaskModel.deleted_at == now,
            )),
            ("subtask", select(SubtaskModel.id).where(
                SubtaskModel.project_id == project_id,
                SubtaskModel.deleted_at == now,
            )),
        ],
        deleted_by=deleted_by,
        now=now,
    )
