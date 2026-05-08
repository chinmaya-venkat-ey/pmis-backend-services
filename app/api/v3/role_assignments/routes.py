"""Routes for doc 41 scoped-RBAC surface.

Three independent FastAPI routers, each with its own prefix. The
``api/router.py`` includes them under ``/api/v3``.

  * ``user_role_assignments_router``    — /users/{user_id}/role-assignments
  * ``project_role_assignments_router`` — /projects/{project_uuid}/role-assignments
  * ``vendor_projects_router``          — /vendors/{vendor_id}/projects
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.dependencies import get_current_user_id
from ....core.middleware.rbac import (
    require_authenticated,
    require_permission,
)
from ....core.permissions import (
    PROJECT_MEMBERS_READ,
    PROJECTS_READ_ALL,
    RBAC_ASSIGN,
    USERS_READ,
    USERS_READ_ALL,
)
from ....core.response import format_error_response
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.models.role import RoleModel
from ....infrastructure.db.models.user import UserModel
from ....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from ....infrastructure.db.models.vendor import VendorModel
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.session import get_db
from .schemas import RoleAssignmentCreateRequest
from .services import (
    can_caller_grant,
    revoke_with_lockout_check,
    serialize_assignment,
)


# ---------------------------------------------------------------------------
# /users/{user_id}/role-assignments
# ---------------------------------------------------------------------------

user_role_assignments_router = APIRouter(
    prefix="/users",
    tags=["role-assignments"],
)


@user_role_assignments_router.get(
    "/{user_id}/role-assignments",
    summary="List a user's role assignments",
    description=(
        "Returns every scoped role assignment held by ``user_id`` "
        "(global, org, project). The user themselves can read their "
        "own list (USERS_READ); admins can read anyone's "
        "(USERS_READ_ALL)."
    ),
)
def list_user_role_assignments(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    # USERS_READ on own, USERS_READ_ALL on others.
    perms = getattr(request.state, "user_permissions", set()) or set()
    if user_id != caller_id and USERS_READ_ALL not in perms:
        if USERS_READ not in perms:
            return BaseController.error(
                format_error_response(
                    "forbidden",
                    "Insufficient permissions to read another user's role assignments.",
                ),
                status=403,
            )
        return BaseController.error(
            format_error_response(
                "forbidden",
                "USERS_READ_ALL is required to read another user's role assignments.",
            ),
            status=403,
        )

    repo = RbacRepository(db)
    rows = repo.list_scoped_assignments_for_user(user_id)
    data = [serialize_assignment(db, r) for r in rows]
    return BaseController.ok(data={"items": data, "total": len(data)})


@user_role_assignments_router.post(
    "/{user_id}/role-assignments",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Grant a scoped role to a user",
    description=(
        "Body: ``{ roleId, projectId? | projectIds? | organizationId? }``. "
        "Use ``projectIds`` (list) to grant the role on multiple projects "
        "in one call — returns ``{items: [...], total: N}`` instead of a "
        "single object. Caller-vs-target rules apply per assignment "
        "(super_admin grants any; admin grants any except super_admin / "
        "admin; org_admin grants project-level roles on projects in their "
        "vendor; project_admin grants project_member on their project). "
        "Batch is all-or-nothing — if any single project fails the "
        "caller-vs-target gate the whole request is refused."
    ),
    status_code=201,
)
def create_user_role_assignment(
    request: Request,
    user_id: str,
    data: RoleAssignmentCreateRequest,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    project_ids = data.project_id_list()
    # Batch path — one row per project, returns a list response.
    if data.projectIds is not None:
        return _create_assignments_batch(
            db,
            target_user_id=user_id,
            role_id=data.roleId,
            project_ids=project_ids,
            caller_id=caller_id,
        )
    # Single-grant path (singular projectId, organizationId, or global).
    return _create_assignment(
        db,
        target_user_id=user_id,
        role_id=data.roleId,
        organization_id=data.organizationId,
        project_id=project_ids[0] if project_ids else None,
        caller_id=caller_id,
    )


@user_role_assignments_router.delete(
    "/{user_id}/role-assignments/{assignment_id}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Revoke a scoped role assignment from a user",
)
def delete_user_role_assignment(
    user_id: str,
    assignment_id: int,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    # Verify the assignment belongs to this user (defensive).
    repo = RbacRepository(db)
    row = repo.get_scoped_assignment(assignment_id)
    if row is None or row.user_id != user_id:
        return BaseController.error(
            format_error_response(
                "not_found",
                f"No role assignment {assignment_id} for user {user_id}.",
            ),
            status=404,
        )
    success, msg, status = revoke_with_lockout_check(
        db, assignment_id, caller_id=caller_id,
    )
    if not success:
        return BaseController.error(
            format_error_response(
                "forbidden" if status == 403 else "not_found", msg,
            ),
            status=status,
        )
    return BaseController.no_content()


# ---------------------------------------------------------------------------
# /projects/{project_uuid}/role-assignments — assignment CRUD + drill-down view
# ---------------------------------------------------------------------------

project_role_assignments_router = APIRouter(
    prefix="/projects",
    tags=["role-assignments"],
)


@project_role_assignments_router.get(
    "/{project_uuid}/role-assignments",
    dependencies=[require_permission(PROJECT_MEMBERS_READ)],
    summary="Per-project role assignments grouped by role",
    description=(
        "Returns the table that powers the FE Project-Mapping mock: "
        "for the given project, the users in each role bucket. Used "
        "by both User-Mgmt and Org-Mgmt menus."
    ),
)
def list_project_role_assignments(
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Join: user_role_assignments → users + roles, filtered to this project.
    rows = (
        db.query(UserRoleAssignmentModel, RoleModel, UserModel)
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .join(UserModel, UserModel.id == UserRoleAssignmentModel.user_id)
        .filter(UserRoleAssignmentModel.project_id == project_uuid)
        .filter(UserModel.deleted_at.is_(None))
        .order_by(RoleModel.name.asc(), UserModel.login.asc())
        .all()
    )

    # Group by role.
    buckets: Dict[int, Dict[str, Any]] = {}
    for ura, role, user in rows:
        bucket = buckets.setdefault(role.id, {
            "roleId": role.id,
            "roleName": role.name,
            "users": [],
        })
        bucket["users"].append({
            "id": user.id,
            "login": user.login,
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name,
            "assignmentId": ura.id,
        })

    project = (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .first()
    )
    return BaseController.ok(data={
        "projectId": project_uuid,
        "projectName": project.name if project else None,
        "roles": list(buckets.values()),
    })


@project_role_assignments_router.post(
    "/{project_uuid}/role-assignments",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Grant a project-scoped role to a user",
    description=(
        "Body: ``{ userId, roleId }``. Always project-scoped — the "
        "project_id comes from the path. Caller-vs-target rules apply."
    ),
    status_code=201,
)
def create_project_role_assignment(
    project_uuid: str,
    data: RoleAssignmentCreateRequest,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    if not data.userId:
        return BaseController.error(
            format_error_response(
                "validation_error",
                "userId is required when creating a project-scoped assignment.",
            ),
            status=422,
        )
    return _create_assignment(
        db,
        target_user_id=data.userId,
        role_id=data.roleId,
        organization_id=None,
        project_id=project_uuid,  # path wins over body
        caller_id=caller_id,
    )


@project_role_assignments_router.delete(
    "/{project_uuid}/role-assignments/{assignment_id}",
    dependencies=[require_permission(RBAC_ASSIGN)],
    summary="Revoke a project-scoped role assignment",
)
def delete_project_role_assignment(
    project_uuid: str,
    assignment_id: int,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    repo = RbacRepository(db)
    row = repo.get_scoped_assignment(assignment_id)
    if row is None or row.project_id != project_uuid:
        return BaseController.error(
            format_error_response(
                "not_found",
                f"No role assignment {assignment_id} on project {project_uuid}.",
            ),
            status=404,
        )
    success, msg, status = revoke_with_lockout_check(
        db, assignment_id, caller_id=caller_id,
    )
    if not success:
        return BaseController.error(
            format_error_response(
                "forbidden" if status == 403 else "not_found", msg,
            ),
            status=status,
        )
    return BaseController.no_content()


# ---------------------------------------------------------------------------
# /vendors/{vendor_id}/projects — Org-Mgmt landing view
# ---------------------------------------------------------------------------

vendor_projects_router = APIRouter(
    prefix="/vendors",
    tags=["role-assignments"],
)


@vendor_projects_router.get(
    "/{vendor_id}/projects",
    dependencies=[require_authenticated()],
    summary="Projects mapped to a vendor (= organization), with role assignments",
    description=(
        "Returns the projects owned by ``vendor_id`` via "
        "``project_vendors``. When ``expand=role-assignments`` is set, "
        "each project carries the same per-role bucket shape returned "
        "by GET /projects/{id}/role-assignments. Powers the Org-Mgmt "
        "landing view."
    ),
)
def list_vendor_projects(
    request: Request,
    vendor_id: str,
    expand: Optional[str] = Query(None, description="'role-assignments' to inline buckets."),
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    # Authorization: PROJECTS_READ_ALL OR org_admin of this vendor.
    perms = getattr(request.state, "user_permissions", set()) or set()
    scoped = getattr(request.state, "scoped_permissions", {}) or {}
    is_global_reader = PROJECTS_READ_ALL in perms
    is_org_scoped = ("org", vendor_id) in scoped
    if not (is_global_reader or is_org_scoped):
        return BaseController.error(
            format_error_response(
                "forbidden",
                "Insufficient permissions to view this organization's projects.",
            ),
            status=403,
        )

    vendor = (
        db.query(VendorModel)
        .filter(VendorModel.id == vendor_id, VendorModel.deleted_at.is_(None))
        .first()
    )
    if vendor is None:
        return BaseController.error(
            format_error_response("not_found", f"Vendor {vendor_id} not found."),
            status=404,
        )

    # Projects mapped to this vendor.
    projects = (
        db.query(ProjectModel)
        .join(ProjectVendorModel, ProjectVendorModel.project_id == ProjectModel.id)
        .filter(ProjectVendorModel.vendor_id == vendor_id)
        .filter(ProjectModel.deleted_at.is_(None))
        .order_by(ProjectModel.name.asc())
        .all()
    )

    expand_assignments = (expand or "").lower() == "role-assignments"
    rows: List[Dict[str, Any]] = []
    for p in projects:
        row: Dict[str, Any] = {
            "projectId": p.id,
            "projectName": p.name,
            "projectStatus": p.status,
        }
        if expand_assignments:
            assignments = (
                db.query(UserRoleAssignmentModel, RoleModel, UserModel)
                .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
                .join(UserModel, UserModel.id == UserRoleAssignmentModel.user_id)
                .filter(UserRoleAssignmentModel.project_id == p.id)
                .filter(UserModel.deleted_at.is_(None))
                .all()
            )
            buckets: Dict[int, Dict[str, Any]] = {}
            for ura, role, user in assignments:
                b = buckets.setdefault(role.id, {
                    "roleId": role.id,
                    "roleName": role.name,
                    "users": [],
                })
                b["users"].append({
                    "id": user.id,
                    "login": user.login,
                    "email": user.email,
                    "assignmentId": ura.id,
                })
            row["roleAssignments"] = list(buckets.values())
        rows.append(row)

    return BaseController.ok(data={
        "vendorId": vendor_id,
        "vendorName": vendor.name,
        "projects": rows,
    })


# ---------------------------------------------------------------------------
# /users/{user_id}/projects — User-Mgmt landing view
# (mounted on the user_role_assignments_router so /users/* shares one prefix)
# ---------------------------------------------------------------------------


@user_role_assignments_router.get(
    "/{user_id}/projects",
    summary="Projects a user is assigned to, with their roles",
    description=(
        "Returns every project that has at least one row in "
        "``user_role_assignments`` for ``user_id``, plus the role "
        "names the user holds on that project. Powers the User-Mgmt "
        "landing view."
    ),
)
def list_user_projects(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    caller_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    perms = getattr(request.state, "user_permissions", set()) or set()
    if user_id != caller_id and USERS_READ_ALL not in perms:
        return BaseController.error(
            format_error_response(
                "forbidden",
                "USERS_READ_ALL is required to read another user's project assignments.",
            ),
            status=403,
        )

    rows = (
        db.query(UserRoleAssignmentModel, RoleModel, ProjectModel)
        .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
        .join(ProjectModel, ProjectModel.id == UserRoleAssignmentModel.project_id)
        .filter(UserRoleAssignmentModel.user_id == user_id)
        .filter(UserRoleAssignmentModel.project_id.isnot(None))
        .filter(ProjectModel.deleted_at.is_(None))
        .order_by(ProjectModel.name.asc())
        .all()
    )
    projects: Dict[str, Dict[str, Any]] = {}
    for ura, role, project in rows:
        p = projects.setdefault(project.id, {
            "projectId": project.id,
            "projectName": project.name,
            "roles": [],
        })
        p["roles"].append(role.name)

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    return BaseController.ok(data={
        "userId": user_id,
        "userLogin": user.login if user else None,
        "projects": list(projects.values()),
    })


# ---------------------------------------------------------------------------
# Internal helper — shared assignment-create path
# ---------------------------------------------------------------------------

def _create_assignment(
    db: Session,
    *,
    target_user_id: str,
    role_id: int,
    organization_id: Optional[str],
    project_id: Optional[str],
    caller_id: str,
) -> Dict[str, Any]:
    # Target user must exist and not be soft-deleted.
    target = (
        db.query(UserModel)
        .filter(UserModel.id == target_user_id, UserModel.deleted_at.is_(None))
        .first()
    )
    if target is None:
        return BaseController.error(
            format_error_response("not_found", f"User {target_user_id} not found."),
            status=404,
        )

    # Role must exist.
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return BaseController.error(
            format_error_response("not_found", f"Role {role_id} not found."),
            status=404,
        )

    # Caller-vs-target gate.
    allowed, reason = can_caller_grant(
        db, caller_id,
        target_role_name=role.name,
        target_organization_id=organization_id,
        target_project_id=project_id,
    )
    if not allowed:
        return BaseController.error(
            format_error_response("forbidden", reason),
            status=403,
        )

    # Resolve scope: project_id wins over body's organization_id when both
    # are passed (the path-driven creation paths always set exactly one).
    if project_id is not None and organization_id is not None:
        organization_id = None

    try:
        row = repo.assign_scoped_role(
            user_id=target_user_id,
            role_id=role_id,
            organization_id=organization_id,
            project_id=project_id,
            actor_id=caller_id,
        )
    except ValueError as exc:
        return BaseController.error(
            format_error_response("validation_error", str(exc)),
            status=422,
        )

    db.commit()
    return BaseController.created(data=serialize_assignment(db, row))


def _create_assignments_batch(
    db: Session,
    *,
    target_user_id: str,
    role_id: int,
    project_ids: List[str],
    caller_id: str,
) -> Dict[str, Any]:
    """Project-scoped batch grant: one row per project, all-or-nothing.

    Validates target user, role, and the caller-vs-target gate for
    EVERY project before any write happens. If any project fails the
    gate, the whole request is rejected with details about which one(s)
    blocked it. Otherwise the rows are written + committed in a single
    transaction.
    """
    target = (
        db.query(UserModel)
        .filter(UserModel.id == target_user_id, UserModel.deleted_at.is_(None))
        .first()
    )
    if target is None:
        return BaseController.error(
            format_error_response("not_found", f"User {target_user_id} not found."),
            status=404,
        )

    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return BaseController.error(
            format_error_response("not_found", f"Role {role_id} not found."),
            status=404,
        )

    # Pre-validate: caller-vs-target gate must pass for every project.
    blocked: List[Dict[str, str]] = []
    for pid in project_ids:
        allowed, reason = can_caller_grant(
            db, caller_id,
            target_role_name=role.name,
            target_organization_id=None,
            target_project_id=pid,
        )
        if not allowed:
            blocked.append({"projectId": pid, "reason": reason})
    if blocked:
        return BaseController.error(
            format_error_response(
                "forbidden",
                "Caller is not authorized to grant on at least one project; no rows written.",
                details={"blocked": blocked},
            ),
            status=403,
        )

    # All gates passed — write each row. ``assign_scoped_role`` is
    # idempotent on (user, role, scope) tuple, so re-running the batch
    # returns the existing rows for projects already granted.
    created_rows = []
    try:
        for pid in project_ids:
            row = repo.assign_scoped_role(
                user_id=target_user_id,
                role_id=role_id,
                organization_id=None,
                project_id=pid,
                actor_id=caller_id,
            )
            created_rows.append(row)
    except ValueError as exc:
        db.rollback()
        return BaseController.error(
            format_error_response("validation_error", str(exc)),
            status=422,
        )

    db.commit()
    items = [serialize_assignment(db, r) for r in created_rows]
    return BaseController.created(data={"items": items, "total": len(items)})
