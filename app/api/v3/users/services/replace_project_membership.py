"""Replace a user's project membership (doc 44 round 9).

Handles ``PATCH /api/v3/users/{id}`` requests that include
``projectIds``. Replaces the user's project_members rows AND their
project-scoped role assignments (doc-41 ``user_role_assignments``)
to match the new list, gated per-row by the caller-vs-target check.

Semantics:
  * ``project_ids = None`` → no-op (leave both tables untouched).
  * ``project_ids = []`` → clear: revoke every project-scoped role
    assignment + delete every project_members row for the user.
  * ``project_ids = [...]`` → diff:
      - revoke project-scoped role assignments whose project_id is
        NOT in the new list,
      - grant project-scoped role assignments for projects that are
        in the new list but missing from existing rows (using the
        user's current orgRole as the role to grant),
      - replace project_members rows to match the new list.

All grants + revokes pass through ``can_caller_grant`` so an
org_admin can only edit memberships on projects within their vendor.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.permissions import (
    DIVISION_MEMBER_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
)
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.project_member import ProjectMemberModel
from .....infrastructure.db.models.role import RoleModel
from .....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from .....infrastructure.db.repositories.rbac_repository import RbacRepository
from .....shared.service_result import ServiceResult


# Project-tier roles whose assignments are keyed by project_id and
# therefore subject to the projectIds replacement diff. org_admin /
# admin / super_admin assignments are not project-scoped — they're
# left alone.
_PROJECT_TIER_ROLES = frozenset({
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
})


def replace_user_project_membership(
    db: Session,
    *,
    user_id: str,
    project_ids: Optional[List[str]],
    caller_id: Optional[str],
) -> ServiceResult:
    """Apply the project-mapping replacement for ``user_id``.

    Returns ``ServiceResult.ok(None)`` on success, or a failed result
    with ``error_type='authorization_error' | 'validation_error'``.
    Caller must commit the session — this helper only flushes.
    """
    # No-op: caller didn't supply projectIds.
    if project_ids is None:
        return ServiceResult.ok(None)

    # Validate projects exist + are not soft-deleted (mirror create.py).
    if project_ids:
        found_ids = {
            row.id for row in
            db.query(ProjectModel)
            .filter(ProjectModel.id.in_(project_ids))
            .filter(ProjectModel.deleted_at.is_(None))
            .all()
        }
        missing = [p for p in project_ids if p not in found_ids]
        if missing:
            return ServiceResult.fail(
                error=f"Project(s) not found or deleted: {', '.join(missing)}",
                error_type="validation_error",
                details={"field": "projectIds", "missing": missing},
            )

    # Existing project-scoped role assignments for this user.
    existing_rows = (
        db.query(UserRoleAssignmentModel, RoleModel)
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .filter(UserRoleAssignmentModel.user_id == user_id)
        .filter(UserRoleAssignmentModel.project_id.isnot(None))
        .filter(RoleModel.name.in_(_PROJECT_TIER_ROLES))
        .all()
    )
    existing_by_pid = {ura.project_id: (ura, role) for ura, role in existing_rows}
    new_set = set(project_ids)

    # Decide which existing assignments to revoke (project removed
    # from new list) and the role to use when granting new rows.
    # Heuristic: if the user has any existing project-tier rows, use
    # the most common role among them as the default for new grants
    # (preserves their tier). If none, fall back to the global
    # orgRole projection.
    rbac = RbacRepository(db)
    to_revoke = [
        (ura, role) for pid, (ura, role) in existing_by_pid.items()
        if pid not in new_set
    ]
    pids_to_add = [pid for pid in project_ids if pid not in existing_by_pid]

    grant_role_name: Optional[str] = None
    if pids_to_add:
        # Most common existing project-tier role wins; else fall back
        # to derive_org_role for the user.
        if existing_by_pid:
            counts: dict = {}
            for _ura, role in existing_by_pid.values():
                counts[role.name] = counts.get(role.name, 0) + 1
            grant_role_name = max(counts, key=counts.get)
        else:
            derived = rbac.derive_org_role(user_id)
            if derived in _PROJECT_TIER_ROLES:
                grant_role_name = derived
            elif derived == ORG_ADMIN_ROLE_NAME:
                # org_admin doesn't take project-scoped rows; can't
                # auto-pick a role. Caller must supply
                # projectAssignments — deferred for round 9.
                return ServiceResult.fail(
                    error=(
                        "Cannot auto-grant project memberships to a user "
                        "without an existing project-tier role and no "
                        "explicit projectAssignments. Use "
                        "POST /users/{id}/role-assignments instead."
                    ),
                    error_type="validation_error",
                )
            else:
                # No prior project-tier role + no derivable tier →
                # default to project_member (the most common case).
                grant_role_name = PROJECT_MEMBER_ROLE_NAME

    # Caller-vs-target gate per row.
    from ...role_assignments.services import can_caller_grant

    if caller_id:
        for ura, role in to_revoke:
            allowed, reason = can_caller_grant(
                db, caller_id,
                target_role_name=role.name,
                target_organization_id=None,
                target_project_id=ura.project_id,
            )
            if not allowed:
                return ServiceResult.fail(
                    error=(
                        f"Caller is not authorized to revoke "
                        f"'{role.name}' on project {ura.project_id}: "
                        + (reason or "scope check failed")
                    ),
                    error_type="authorization_error",
                )
        if grant_role_name and pids_to_add:
            for pid in pids_to_add:
                allowed, reason = can_caller_grant(
                    db, caller_id,
                    target_role_name=grant_role_name,
                    target_organization_id=None,
                    target_project_id=pid,
                )
                if not allowed:
                    return ServiceResult.fail(
                        error=(
                            f"Caller is not authorized to grant "
                            f"'{grant_role_name}' on project {pid}: "
                            + (reason or "scope check failed")
                        ),
                        error_type="authorization_error",
                    )

    # Apply revokes.
    for ura, _role in to_revoke:
        db.delete(ura)

    # Apply grants.
    if grant_role_name and pids_to_add:
        role_id = (
            db.query(RoleModel)
            .filter(RoleModel.name == grant_role_name)
            .one().id
        )
        for pid in pids_to_add:
            rbac.assign_scoped_role(
                user_id=user_id,
                role_id=role_id,
                organization_id=None,
                project_id=pid,
                actor_id=caller_id,
            )

    # Replace project_members rows. Simple wipe + insert — the table
    # is small per user and this is the same approach create uses on
    # initial bind.
    db.query(ProjectMemberModel).filter(
        ProjectMemberModel.user_id == user_id,
    ).delete(synchronize_session=False)
    for pid in project_ids:
        db.add(ProjectMemberModel(
            project_id=pid, user_id=user_id, roles=[],
        ))

    db.flush()
    return ServiceResult.ok(None)
