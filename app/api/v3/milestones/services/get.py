"""Fetch a single milestone by id."""
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.milestones.milestone import Milestone
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository


def get_milestone(db: Session, milestone_id: str, include_deleted: bool = False) -> Milestone:
    m = MilestoneRepository(db).get_by_id(milestone_id, include_deleted=include_deleted)
    if m is None:
        raise NotFoundError("The milestone could not be found.")
    return m
