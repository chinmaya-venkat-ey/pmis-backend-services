"""
Project list service.
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....domain.projects.project import Project
from .....shared.service_result import ServiceResult
from .....shared.pagination import PaginatedResult, calculate_offset


def list_projects(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    active: Optional[bool] = None,
    public: Optional[bool] = None,
    include_deleted: bool = False,
) -> ServiceResult[PaginatedResult[Project]]:
    """
    List projects with pagination and optional filtering.

    ``include_deleted=False`` (default) returns only live rows — backs the
    Search Project view. ``include_deleted=True`` returns every row including
    soft-deleted ones — backs the admin "all projects" audit view.
    """
    # Validate pagination parameters
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    if page_size > 100:
        page_size = 100

    repository = ProjectRepository(db)
    offset = calculate_offset(page, page_size)

    # Build query with filters
    try:
        query = db.query(ProjectModel)
        if not include_deleted:
            query = query.filter(ProjectModel.deleted_at.is_(None))

        if active is not None:
            query = query.filter(ProjectModel.active == active)
        if public is not None:
            query = query.filter(ProjectModel.public == public)

        # Get total count
        total = query.count()

        # Newest-first ordering. The Search Project table reads top-down, so
        # the most recently created project should land at row 0. Tie-break on
        # id to keep pagination stable when two rows share a created_at
        # timestamp (possible on bulk seeds).
        query = query.order_by(
            ProjectModel.created_at.desc(),
            ProjectModel.id.desc(),
        )

        # Get paginated results
        models = query.offset(offset).limit(page_size).all()
        projects = [repository._to_domain(m) for m in models]

        result = PaginatedResult(
            items=projects,
            total=total,
            page=page,
            page_size=page_size,
        )

        return ServiceResult.ok(result)

    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to list projects: {str(e)}",
            error_type="internal_error"
        )
