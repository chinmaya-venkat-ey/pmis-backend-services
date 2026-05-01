"""List milestones under a project (paginated)."""
from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError
from .....domain.milestones.milestone import Milestone
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.milestone_repository import MilestoneRepository


@dataclass
class PagedMilestones:
    items: List[Milestone]
    total: int
    page: int
    page_size: int


def list_milestones(
    db: Session, *, project_id: str, page: int, page_size: int, include_deleted: bool,
) -> PagedMilestones:
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if project is None:
        raise NotFoundError("The project could not be found.")
    # Respect project-level soft delete if the column exists.
    if getattr(project, "deleted_at", None) is not None:
        raise NotFoundError("The project has been deleted.")

    offset = max(page - 1, 0) * page_size
    items, total = MilestoneRepository(db).list_by_project(
        project_id=project_id, offset=offset, limit=page_size,
        include_deleted=include_deleted,
    )
    return PagedMilestones(items=items, total=total, page=page, page_size=page_size)
