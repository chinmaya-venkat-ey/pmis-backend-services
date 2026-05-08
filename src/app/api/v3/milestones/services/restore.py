"""Restore a soft-deleted milestone (admin)."""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_project_editable
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository
from .....domain.milestones.milestone import Milestone


def restore_milestone(db: Session, *, milestone_id: str, current_user_id: Optional[int]) -> Milestone:
    repo = MilestoneRepository(db)
    model = repo.get_model(milestone_id, include_deleted=True)
    if model is None:
        raise NotFoundError("The milestone could not be found.")
    if model.deleted_at is None:
        raise ValidationError(
            "This milestone is already active and does not need to be restored."
        )

    # Refuse to restore into a locked project (published baseline / deleted project).
    assert_project_editable(db, model.project_id)

    return repo.restore(milestone_id, restored_by=current_user_id)
