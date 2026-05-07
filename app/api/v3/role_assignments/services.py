"""Role-assignment business logic (doc 41).

The route layer is intentionally thin (`require_permission(RBAC_ASSIGN)`
+ schema validation). The caller-vs-target gates — "can THIS caller
grant THAT role at THIS scope?" — live here.

Caller-vs-target rules (doc 41 §"Caller-vs-target authorization"):

  * super_admin   — any role at any scope (only one who can grant super_admin)
  * admin         — any role except super_admin
  * org_admin (X) — project_admin / project_member / division_member on
                    projects whose owning vendor is X
  * project_admin (P) — project_member only, scoped to project P
  * anyone else   — nothing

The lockout-protection guards layered on top:

  * The last super_admin cannot be revoked.
  * A user cannot revoke their OWN super_admin assignment (covered by
    the "last super_admin" check, but stated explicitly so the error
    message is helpful).
"""
from datetime import timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ....core.permissions import (
    ADMIN_ROLE_NAME,
    ORG_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
    USERS_GRANT_SUPERADMIN,
)
from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.models.role import RoleModel
from ....infrastructure.db.models.user import UserModel
from ....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from ....infrastructure.db.repositories.rbac_repository import RbacRepository


# Role names this doc grants — the rule table only addresses these.
# Granting any other role (e.g. legacy 'admin'/'member'/'viewer'/'vendor')
# requires the caller to hold ``rbac:assign`` globally; sub-admin tiers
# can only grant the doc-41 scoped roles.
_DOC41_SCOPED_ROLES = (
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
)
_DOC41_ORG_GRANTABLE = (
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_NAME,
)
_DOC41_PROJECT_ADMIN_GRANTABLE = (PROJECT_MEMBER_ROLE_NAME,)


# ---------------------------------------------------------------------------
# Caller capability detection — derived from the caller's existing scoped
# assignments. We don't trust the union (too coarse) — we look at the
# specific role rows.
# ---------------------------------------------------------------------------

def _caller_role_names_at_scope(
    db: Session, caller_id: str,
) -> Tuple[set, dict, dict]:
    """Return (global_roles, project_roles, org_roles) sets for the caller.

    ``project_roles`` is ``Dict[project_id, set(role_name)]``;
    ``org_roles`` is ``Dict[organization_id, set(role_name)]``.
    Used by :func:`can_caller_grant`.
    """
    repo = RbacRepository(db)
    rows = (
        db.query(UserRoleAssignmentModel, RoleModel)
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .filter(UserRoleAssignmentModel.user_id == caller_id)
        .all()
    )
    global_roles: set = set()
    project_roles: dict = {}
    org_roles: dict = {}
    for ura, role in rows:
        if ura.project_id:
            project_roles.setdefault(ura.project_id, set()).add(role.name)
        elif ura.organization_id:
            org_roles.setdefault(ura.organization_id, set()).add(role.name)
        else:
            global_roles.add(role.name)
    # Doc 41 also honours legacy user_roles for backwards-compat — anyone
    # holding the legacy 'admin' or 'super_admin' there gets global power.
    if repo.user_has_super_admin_role(caller_id):
        global_roles.add(SUPER_ADMIN_ROLE_NAME)
    if repo.user_has_admin_role(caller_id):
        global_roles.add(ADMIN_ROLE_NAME)
    return global_roles, project_roles, org_roles


def _project_owning_vendors(db: Session, project_id: str) -> List[str]:
    """Return vendor_ids that own the project via project_vendors."""
    rows = (
        db.query(ProjectVendorModel.vendor_id)
        .filter(ProjectVendorModel.project_id == project_id)
        .all()
    )
    return [r[0] for r in rows]


def can_caller_grant(
    db: Session,
    caller_id: str,
    *,
    target_role_name: str,
    target_organization_id: Optional[str],
    target_project_id: Optional[str],
) -> Tuple[bool, str]:
    """Return (allowed, reason) for a grant attempt.

    ``reason`` is the human-readable rejection string when ``allowed``
    is False; empty string on allow.
    """
    global_roles, project_roles, org_roles = _caller_role_names_at_scope(
        db, caller_id,
    )

    # super_admin can grant anything anywhere.
    if SUPER_ADMIN_ROLE_NAME in global_roles:
        return True, ""

    # Granting super_admin requires super_admin (already gated above).
    if target_role_name == SUPER_ADMIN_ROLE_NAME:
        return False, (
            "Only super_admin can grant the super_admin role."
        )

    # admin can grant anything except super_admin.
    if ADMIN_ROLE_NAME in global_roles:
        return True, ""

    # org_admin (of X) — only on projects owned by X, and only the
    # 3 scoped sub-roles.
    if target_project_id is not None and target_role_name in _DOC41_ORG_GRANTABLE:
        owning_vendors = set(_project_owning_vendors(db, target_project_id))
        callers_orgs_as_admin = {
            org_id for org_id, names in org_roles.items()
            if ORG_ADMIN_ROLE_NAME in names
        }
        if owning_vendors & callers_orgs_as_admin:
            return True, ""

    # project_admin (of P) — only project_member, only on P.
    if (
        target_project_id is not None
        and target_role_name in _DOC41_PROJECT_ADMIN_GRANTABLE
    ):
        names = project_roles.get(target_project_id, set())
        if PROJECT_ADMIN_ROLE_NAME in names:
            return True, ""

    return False, (
        "Caller is not authorized to grant this role at this scope."
    )


def serialize_assignment(
    db: Session, assignment: UserRoleAssignmentModel,
) -> dict:
    role = (
        db.query(RoleModel)
        .filter(RoleModel.id == assignment.role_id)
        .first()
    )
    user = (
        db.query(UserModel)
        .filter(UserModel.id == assignment.user_id)
        .first()
    )
    if assignment.project_id:
        scope = "project"
    elif assignment.organization_id:
        scope = "org"
    else:
        scope = "global"
    return {
        "id": assignment.id,
        "userId": assignment.user_id,
        "userLogin": user.login if user else None,
        "userEmail": user.email if user else None,
        "roleId": assignment.role_id,
        "roleName": role.name if role else None,
        "organizationId": assignment.organization_id,
        "projectId": assignment.project_id,
        "scope": scope,
        "createdAt": (
            assignment.created_at.replace(tzinfo=timezone.utc).isoformat()
            if assignment.created_at and assignment.created_at.tzinfo is None
            else assignment.created_at.isoformat() if assignment.created_at
            else None
        ),
        "createdBy": assignment.created_by,
    }


def revoke_with_lockout_check(
    db: Session, assignment_id: int, *, caller_id: Optional[str],
) -> Tuple[bool, str, int]:
    """Revoke an assignment with the last-super_admin guard.

    Returns (success, message, status_code). ``status_code`` is the
    HTTP status the route should surface.
    """
    repo = RbacRepository(db)
    row = repo.get_scoped_assignment(assignment_id)
    if row is None:
        return False, "Assignment not found.", 404

    # If the assignment we're about to revoke is the LAST global
    # super_admin row, refuse — would lock everyone out of granting
    # the role again.
    role = db.query(RoleModel).filter(RoleModel.id == row.role_id).first()
    if (
        role is not None
        and role.name == SUPER_ADMIN_ROLE_NAME
        and row.organization_id is None
        and row.project_id is None
    ):
        if repo.count_global_super_admins() <= 1:
            return (
                False,
                "Cannot revoke the last global super_admin — at least one "
                "super_admin must remain to grant the role to others.",
                403,
            )

    repo.revoke_scoped_assignment(assignment_id)
    db.commit()
    return True, "", 204
