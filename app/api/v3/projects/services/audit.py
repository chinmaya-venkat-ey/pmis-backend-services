"""
Project audit recording.

Callers invoke ``record_audit`` inside the transaction that made the change.
The audit row is flushed (so it's visible to later queries in the same tx)
but not committed — the caller owns the transaction boundary.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from .....domain.projects.project import Project
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.role import RoleModel
from .....infrastructure.db.models.user import UserModel
from .....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from .....infrastructure.db.repositories.project_audit_log_repository import (
    ProjectAuditLogRepository,
)


# Highest-tier wins. Mirrors the priority list used by
# /api/v3/projects/{id}/assignable-users so the audit role bucket is
# consistent with what the FE picker shows for the same user.
_ROLE_PRIORITY = (
    "super_admin",
    "admin",
    "org_admin",
    "project_admin",
    "project_member",
    "division_member",
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


def _resolve_actor_login(db: Session, actor_id: Optional[str]) -> Dict[str, str]:
    """Look up the user's login + user_code for snapshotting.

    Returns a two-key dict. For unauth/system actions both fall back
    to 'system'.
    """
    if not actor_id:
        return {"login": "system", "user_code": "system"}
    row = (
        db.query(UserModel.login, UserModel.user_code)
        .filter(UserModel.id == actor_id)
        .first()
    )
    if not row:
        return {"login": "system", "user_code": "system"}
    return {"login": row[0] or "system", "user_code": row[1] or "system"}


def _resolve_actor_role(db: Session, actor_id: Optional[str]) -> str:
    """Derive the role bucket the actor currently holds.

    Mirrors the same logic the /projects/{id}/assignable-users endpoint
    uses: pick the highest tier in :data:`_ROLE_PRIORITY` that appears
    in the user's ``user_role_assignments`` rows; fall back to the
    denormalized ``users.org_role`` column (round 9b); fall back to
    ``'user'`` for an authenticated user with no role grants at all;
    only return ``'system'`` when there's literally no actor.

    Resolution happens at audit-write time, which captures the user's
    effective role bucket inside the same transaction as the change
    being audited. If you need request-time fidelity instead (e.g.
    capture the role the auth middleware actually granted for THIS
    request rather than the user's current grants), pass
    ``actor_role`` explicitly into :func:`record_audit` from the
    handler.
    """
    if not actor_id:
        return "system"

    # 1) Highest-tier scoped role assignment.
    held = {
        n for (n,) in (
            db.query(RoleModel.name)
            .join(
                UserRoleAssignmentModel,
                UserRoleAssignmentModel.role_id == RoleModel.id,
            )
            .filter(UserRoleAssignmentModel.user_id == actor_id)
            .distinct()
            .all()
        )
    }
    for tier in _ROLE_PRIORITY:
        if tier in held:
            return tier

    # 2) Round-9b denormalized column on users.
    org_role = (
        db.query(UserModel.org_role)
        .filter(UserModel.id == actor_id)
        .scalar()
    )
    if org_role and org_role in _ROLE_PRIORITY:
        return org_role

    # 3) Authenticated, but no role bucket on file — distinguish from
    #    system actions so the audit reader can tell them apart.
    return "user"


def _resolve_project_snapshot_fields(
    db: Session, project_id: str
) -> Dict[str, str]:
    """Snapshot name / status / owner from the project row at write time.

    These get persisted on the audit row so the log stays meaningful
    even if the project is later renamed, closed, or has its owner
    flipped. Returns '(unknown)' for missing values so the NOT NULL
    columns are always populated.
    """
    row = (
        db.query(
            ProjectModel.name,
            ProjectModel.status,
            ProjectModel.owner,
        )
        .filter(ProjectModel.id == project_id)
        .first()
    )
    if row is None:
        return {
            "project_name": "(unknown)",
            "project_status": "(unknown)",
            "owner": "(unknown)",
        }
    return {
        "project_name": row[0] or "(unknown)",
        "project_status": row[1] or "(unknown)",
        "owner": row[2] or "(unknown)",
    }


def record_audit(
    db: Session,
    project_id: str,
    actor_id: Optional[str],
    action: str,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    actor_role: Optional[str] = None,
) -> None:
    """Persist one audit log row.

    Doc 47: in addition to the original (project_id, actor_id, action,
    before, after) tuple, the row now carries denormalized snapshots
    of the project's name/status/owner and the actor's login + user_code —
    captured at write time so the log row stays correct even if those
    source rows mutate afterwards. All five are NOT NULL on the table;
    we resolve them here so call sites don't have to know.
    """
    proj_fields = _resolve_project_snapshot_fields(db, project_id)
    actor_fields = _resolve_actor_login(db, actor_id)
    # actor_role: callers can pass it explicitly (request-time role
    # bucket); otherwise we derive at audit-write time from the user's
    # role assignments. 'system' is reserved for actor_id=None.
    resolved_role = actor_role if actor_role else _resolve_actor_role(db, actor_id)
    ProjectAuditLogRepository(db).add(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        before=before,
        after=after,
        actor_role=resolved_role,
        actor_login=actor_fields["login"],
        actor_code=actor_fields["user_code"],
        project_name=proj_fields["project_name"],
        project_status=proj_fields["project_status"],
        owner=proj_fields["owner"],
    )
