"""
Project read service.
"""
from sqlalchemy.orm import Session
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....domain.projects.project import Project
from .....shared.service_result import ServiceResult


def get_project_by_id(db: Session, project_id: str) -> ServiceResult[Project]:
    """Get project by its UUID id (the public handle)."""
    repository = ProjectRepository(db)
    project = repository.get_by_id(project_id)
    if not project:
        return ServiceResult.fail(
            error="The project could not be found.",
            error_type="not_found",
        )
    return ServiceResult.ok(project)
