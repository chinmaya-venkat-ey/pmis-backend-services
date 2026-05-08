"""Fetch a single activity (+ optional resource)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.activities.activity import Activity
from .....domain.activities.activity_resource import ActivityResource
from .....infrastructure.db.repositories.activity_repository import ActivityRepository
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)


def get_activity(db: Session, activity_id: str, include_deleted: bool = False) -> Activity:
    a = ActivityRepository(db).get_by_id(activity_id, include_deleted=include_deleted)
    if a is None:
        raise NotFoundError("The activity could not be found.")
    a.depends_on = DependencyRepository(db).list_activity_dependencies(activity_id)
    return a


def get_activity_with_resource(
    db: Session, activity_id: str, include_deleted: bool = False,
) -> Tuple[Activity, Optional[ActivityResource]]:
    repo = ActivityRepository(db)
    a = repo.get_by_id(activity_id, include_deleted=include_deleted)
    if a is None:
        raise NotFoundError("The activity could not be found.")
    res = repo.get_live_resource(activity_id) if a.type == "resource" else None
    a.depends_on = DependencyRepository(db).list_activity_dependencies(activity_id)
    return a, res
