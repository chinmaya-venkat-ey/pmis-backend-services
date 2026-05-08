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
#
# Doc 33: with versioning removed, ACTION_SUSPEND and ACTION_VERSION_CREATE
# are gone. Audit coverage was expanded to include the M/A/T/S subtree
# writes plus dependency, status, vendor-association and member-association
# changes — every state change to a project is captured here regardless of
# which subtree handler made it.
ACTION_CREATE = "project.create"
ACTION_UPDATE = "project.update"
ACTION_PUBLISH = "project.publish"
ACTION_CLOSE = "project.close"
ACTION_SOFT_DELETE = "project.soft_delete"
ACTION_DRAFT = "project.draft"
ACTION_STATUS_CHANGE = "project.status_change"

# Subtree write actions (doc 33 audit expansion).
ACTION_MILESTONE_CREATE = "milestone.create"
ACTION_MILESTONE_UPDATE = "milestone.update"
ACTION_MILESTONE_DELETE = "milestone.soft_delete"
ACTION_MILESTONE_DEP_CHANGE = "milestone.dep_change"
ACTION_ACTIVITY_CREATE = "activity.create"
ACTION_ACTIVITY_UPDATE = "activity.update"
ACTION_ACTIVITY_DELETE = "activity.soft_delete"
ACTION_ACTIVITY_DEP_CHANGE = "activity.dep_change"
ACTION_TASK_CREATE = "task.create"
ACTION_TASK_UPDATE = "task.update"
ACTION_TASK_DELETE = "task.soft_delete"
ACTION_TASK_DEP_CHANGE = "task.dep_change"
ACTION_SUBTASK_CREATE = "subtask.create"
ACTION_SUBTASK_UPDATE = "subtask.update"
ACTION_SUBTASK_DELETE = "subtask.soft_delete"
ACTION_SUBTASK_DEP_CHANGE = "subtask.dep_change"

# Project-association actions (doc 33 audit expansion).
ACTION_VENDOR_ASSOC_ADD = "project.vendor.assoc_add"
ACTION_VENDOR_ASSOC_REMOVE = "project.vendor.assoc_remove"
ACTION_MEMBER_ADD = "project.member.add"
ACTION_MEMBER_UPDATE = "project.member.update"
ACTION_MEMBER_REMOVE = "project.member.remove"


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
    }


def record_audit(
    db: Session,
    project_id: str,
    actor_id: Optional[str],
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
