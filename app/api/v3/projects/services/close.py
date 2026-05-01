"""
Close a project (any non-closed status -> closed). Admin-only at endpoint.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....core.errors import ValidationError
from .....domain.projects.project import Project
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_CLOSE, project_snapshot, record_audit
from .transitions import STATUS_CLOSED, assert_transition_allowed


def close_project(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[int],
    actor_is_admin: bool,
    reason: Optional[str] = None,
) -> ServiceResult[Project]:
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    if (project.status or "").lower() == STATUS_CLOSED:
        return ServiceResult.fail(
            error="Project is already closed",
            error_type="invalid_transition",
            details={"errorIdentifier": "invalid_transition", "from": project.status, "to": STATUS_CLOSED},
        )

    try:
        assert_transition_allowed(
            from_status=project.status,
            to_status=STATUS_CLOSED,
            actor_is_admin=actor_is_admin,
            project_is_version=project.is_version,
            db=db,
        )
    except ValidationError as e:
        return ServiceResult.fail(
            error=e.message,
            error_type=e.details.get("errorIdentifier", "invalid_transition"),
            details=e.details,
        )

    before = project_snapshot(project)

    try:
        patch = {"status": STATUS_CLOSED}
        if reason:
            patch["status_explanation"] = reason
        updated = repo.update(project_id=project_id, updated_by=actor_id, **patch)
        if updated is None:
            return ServiceResult.fail(
                error=f"Project with ID {project_id} not found",
                error_type="not_found",
            )

        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_CLOSE,
            before=before,
            after=project_snapshot(updated),
        )

        db.commit()
        return ServiceResult.ok(updated)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to close project: {str(e)}",
            error_type="internal_error",
        )
