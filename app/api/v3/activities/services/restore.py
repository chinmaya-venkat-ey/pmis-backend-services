"""Restore a soft-deleted activity (admin). Parent milestone must be live."""
from typing import Optional
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_project_editable
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.repositories.activity_repository import ActivityRepository
from .....domain.activities.activity import Activity


def restore_activity(db: Session, *, activity_id: str, current_user_id: Optional[int]) -> Activity:
    repo = ActivityRepository(db)
    model = repo.get_model(activity_id, include_deleted=True)
    if model is None:
        raise NotFoundError("The activity could not be found.")
    if model.deleted_at is None:
        raise ValidationError(
            "This activity is already active and does not need to be restored."
        )

    # Parent milestone must be live -- otherwise the activity would be
    # orphaned under a soft-deleted parent.
    parent = (
        db.query(MilestoneModel)
        .filter(MilestoneModel.id == model.milestone_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .first()
    )
    if parent is None:
        raise ValidationError(
            "The milestone this activity belongs to has been deleted. "
            "Please restore the milestone first."
        )

    assert_project_editable(db, model.project_id)
    restored = repo.restore(activity_id, restored_by=current_user_id)
    # Restored activities start with empty dep list (cascade-on-delete wiped
    # their edges; admins must re-attach if desired).
    restored.depends_on = []
    return restored
