"""
Project soft-delete service.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....api.v3.milestones.services.cascade import cascade_soft_delete_project
from .....infrastructure.db.models.project_vendor import ProjectVendorModel
from .....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_SOFT_DELETE, project_snapshot, record_audit
from .transitions import STATUS_CLOSED


def _disconnect_associations(db: Session, project_id: str) -> None:
    """Remove vendor + member mapping rows for a deleted project.

    Per product rule: a deleted project should appear disconnected from any
    vendor or user in every downstream view. We delete the association rows
    rather than soft-flagging them because the project itself carries the
    only flag we need (``deleted_at``); leaving the mapping rows behind would
    require every join elsewhere to filter out deleted projects, which is
    error-prone. Audit history of the project itself preserves the snapshot
    of what was attached at delete time.
    """
    db.query(ProjectVendorModel).filter(
        ProjectVendorModel.project_id == project_id
    ).delete(synchronize_session=False)
    # Project-scoped role assignments (the unified membership table
    # after the project_members migration). URA's CHECK constraint
    # ensures project_id IS NOT NULL implies organization_id is null,
    # so this delete only touches project-scoped rows.
    db.query(UserRoleAssignmentModel).filter(
        UserRoleAssignmentModel.project_id == project_id
    ).delete(synchronize_session=False)


def delete_project(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[str],
) -> ServiceResult[None]:
    """
    Soft-delete a project: stamp ``deleted_at`` / ``deleted_by``, flip status
    to ``closed``, drop vendor + member mapping rows, and cascade the delete
    through the M/A/T/S subtree. One transaction — no partial state.

    Doc 33: with the versioning feature removed, the cascade-to-versions
    branch is gone — there are no version rows to cascade to. A project
    is just a project.

    Per decision: admin-only permission is the gate; we do NOT call
    ``assert_project_editable`` — deletion is available even on published
    projects.
    """
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    try:
        before = project_snapshot(project)
        repo.soft_delete(project_id, actor_id=actor_id)
        repo.update(
            project_id=project_id,
            updated_by=actor_id,
            include_deleted=True,
            status=STATUS_CLOSED,
        )
        _disconnect_associations(db, project_id)
        cascade_soft_delete_project(db, project_id, actor_id)
        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_SOFT_DELETE,
            before=before,
            after=None,
        )

        db.commit()
        return ServiceResult.ok(None)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to delete project: {str(e)}",
            error_type="internal_error",
        )
