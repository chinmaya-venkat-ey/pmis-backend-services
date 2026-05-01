"""
Suspend a version project. Versions only. Terminal — suspended versions do
not come back (new version must be created from the baseline instead).
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....core.errors import ValidationError
from .....domain.projects.project import Project
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_SUSPEND, project_snapshot, record_audit
from .transitions import STATUS_SUSPENDED, assert_transition_allowed


def suspend_version(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[int],
    actor_is_admin: bool,
) -> ServiceResult[Project]:
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    if not project.is_version:
        return ServiceResult.fail(
            error="Only version projects can be suspended",
            error_type="invalid_transition",
            details={"errorIdentifier": "invalid_transition", "reason": "version_only"},
        )

    if (project.status or "").lower() == STATUS_SUSPENDED:
        return ServiceResult.fail(
            error="Version is already suspended",
            error_type="invalid_transition",
            details={"errorIdentifier": "invalid_transition", "from": project.status, "to": STATUS_SUSPENDED},
        )

    try:
        assert_transition_allowed(
            from_status=project.status,
            to_status=STATUS_SUSPENDED,
            actor_is_admin=actor_is_admin,
            project_is_version=True,
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
        updated = repo.update(
            project_id=project_id,
            status=STATUS_SUSPENDED,
            updated_by=actor_id,
        )
        if updated is None:
            return ServiceResult.fail(
                error=f"Project with ID {project_id} not found",
                error_type="not_found",
            )

        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_SUSPEND,
            before=before,
            after=project_snapshot(updated),
        )

        db.commit()
        return ServiceResult.ok(updated)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to suspend version: {str(e)}",
            error_type="internal_error",
        )
