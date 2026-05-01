"""
Project audit recording.

Callers invoke ``record_audit`` inside the transaction that made the change.
The audit row is flushed (so it's visible to later queries in the same tx)
but not committed — the caller owns the transaction boundary.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .....domain.projects.project import Project
from .....infrastructure.db.repositories.project_audit_log_repository import (
    ProjectAuditLogRepository,
)


# Well-known action names. Callers should use these rather than raw strings
# so downstream log viewers stay consistent.
ACTION_CREATE = "project.create"
ACTION_UPDATE = "project.update"
ACTION_PUBLISH = "project.publish"
ACTION_CLOSE = "project.close"
ACTION_SUSPEND = "project.suspend"
ACTION_VERSION_CREATE = "project.version.create"
ACTION_SOFT_DELETE = "project.soft_delete"
ACTION_DRAFT = "project.draft"


def project_snapshot(project: Project) -> Dict[str, Any]:
    """Project fields captured for the audit ``before`` / ``after`` payload."""
    return {
        "status": project.status,
        "name": project.name,
        "description": project.description,
        "owner": project.owner,
        "public": project.public,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "actual_start_date": (
            project.actual_start_date.isoformat() if project.actual_start_date else None
        ),
        "actual_end_date": (
            project.actual_end_date.isoformat() if project.actual_end_date else None
        ),
        "category": project.category,
        "is_version": project.is_version,
        "version_of": project.version_of,
        "baseline_id": project.baseline_id,
        "version_no": project.version_no,
    }


def record_audit(
    db: Session,
    project_id: str,
    actor_id: Optional[int],
    action: str,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> None:
    ProjectAuditLogRepository(db).add(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        before=before,
        after=after,
    )
