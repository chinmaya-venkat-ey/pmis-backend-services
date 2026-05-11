"""
Project routes - URL definitions with permission bindings.

All URL path parameters use ``project_uuid`` (the public handle). The
controller resolves UUID -> internal id.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import NotFoundError
from ....core.middleware.rbac import require_permission
from ....core.permissions import PROJECT_MEMBERS_READ
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.models.role import RoleModel
from ....infrastructure.db.models.user import UserModel
from ....infrastructure.db.models.user_role import UserRoleModel
from ....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from ....infrastructure.db.session import get_db

from .controller import ProjectController
from .permissions import (
    PROJECTS_CLOSE,
    PROJECTS_CREATE,
    PROJECTS_DELETE_ALL,
    PROJECTS_PUBLISH,
    PROJECTS_READ,
    PROJECTS_UPDATE,
)
from .schemas import (
    ProjectCloseRequest,
    ProjectCreateRequest,
    ProjectListQuery,
    ProjectUpdateRequest,
    ProjectUpsertRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "/create",
    dependencies=[require_permission(PROJECTS_CREATE)],
    summary="Create project",
    status_code=201,
)
def create_project(
    request: Request,
    data: ProjectCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.create(request, data, db)


@router.put(
    "/{project_uuid}",
    dependencies=[require_permission(PROJECTS_CREATE)],
    summary="Create or update project by uuid (idempotent)",
    description=(
        "Idempotent create-or-update of a project keyed by uuid. Used by "
        "multi-step creation wizards — re-submitting the same uuid updates "
        "the existing row rather than creating a duplicate. Returns 201 on "
        "first call, 200 on subsequent calls; on the update path, caller "
        "must own the project (or be admin). The frontend generates the uuid "
        "via crypto.randomUUID() once per wizard session. The server "
        "auto-generates projectCode on insert and preserves it on update."
    ),
)
def upsert_project_by_uuid(
    request: Request,
    project_uuid: str,
    data: ProjectUpsertRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.upsert(request, project_uuid, data, db)


@router.get(
    "",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="List live projects (excludes soft-deleted)",
    description=(
        "Default Search Project listing. Soft-deleted projects are filtered "
        "out; results are newest-first (createdAt descending). For the "
        "admin view that includes deleted rows, see GET /projects/all."
    ),
)
def list_projects(
    request: Request,
    offset: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    active: bool = Query(None),
    public: bool = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query = ProjectListQuery(
        offset=offset, pageSize=pageSize, active=active, public=public,
        includeDeleted=False,
    )
    return ProjectController.list(request, query, db)


@router.get(
    "/all",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="List all projects including soft-deleted",
    description=(
        "Admin / audit view. Returns every project row, including those that "
        "have been soft-deleted. Each row carries a `deletedAt` field — NULL "
        "for live projects, populated for deleted ones. Sort order is the "
        "same newest-first ordering used by GET /projects."
    ),
)
def list_all_projects(
    request: Request,
    offset: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    active: bool = Query(None),
    public: bool = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query = ProjectListQuery(
        offset=offset, pageSize=pageSize, active=active, public=public,
        includeDeleted=True,
    )
    return ProjectController.list(request, query, db)


@router.get(
    "/{project_uuid}",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="Get project",
)
def get_project(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.get(request, project_uuid, db)


@router.patch(
    "/{project_uuid}",
    dependencies=[require_permission(PROJECTS_UPDATE)],
    summary="Update project",
)
def update_project(
    request: Request,
    project_uuid: str,
    data: ProjectUpdateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.update(request, project_uuid, data, db)


@router.delete(
    "/{project_uuid}",
    dependencies=[require_permission(PROJECTS_DELETE_ALL)],
    summary="Soft-delete project",
)
def delete_project(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.delete(request, project_uuid, db)


@router.post(
    "/{project_uuid}/save",
    dependencies=[require_permission(PROJECTS_UPDATE)],
    summary="Save project setup (new -> draft if milestones exist)",
    description=(
        "Maps to the 'Save Project' button in the Step-1 wizard. Flips status "
        "from 'new' to 'draft' when at least one live milestone exists on the "
        "project. Adding a milestone alone does NOT change status — only this "
        "explicit save call does. Idempotent: a no-op once past 'new'."
    ),
)
def save_project(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.save(request, project_uuid, db)


@router.post(
    "/{project_uuid}/publish",
    dependencies=[require_permission(PROJECTS_PUBLISH)],
    summary="Publish project",
)
def publish_project(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.publish(request, project_uuid, db)


@router.post(
    "/{project_uuid}/close",
    dependencies=[require_permission(PROJECTS_CLOSE)],
    summary="Close project",
)
def close_project(
    request: Request,
    project_uuid: str,
    data: Optional[ProjectCloseRequest] = Body(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ProjectController.close(request, project_uuid, data, db)


@router.get(
    "/{project_uuid}/assignable-users",
    dependencies=[require_permission(PROJECT_MEMBERS_READ)],
    summary="Users that can be assigned a Task / Sub-Task on this project",
    description=(
        "Round 11b (mirrored from monolith): returns the union of "
        "(a) every user with a project-tier role assignment on this "
        "project (project_admin, project_member, division_member) AND "
        "(b) every user with an org_admin role assignment on the "
        "project's owning vendor(s). OAs are included so a "
        "project_admin can assign tasks up to an org admin per spec. "
        "The set is de-duplicated by user id. Each entry carries "
        "``id`` / ``login`` / ``firstName`` / ``lastName`` / ``email`` "
        "/ ``orgRole`` so the FE picker can render names without a "
        "per-id /users round-trip.\n\n"
        "Round 11b hotfix: admin / super_admin (in any form — legacy "
        "user_roles OR global user_role_assignments) are excluded "
        "from the response. They don't go in project pickers, even "
        "if they also hold a project-tier assignment on this project."
    ),
)
def list_project_assignable_users(
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Round-9b: round-trippable orgRole from the column when no role
    # assignment matches.
    _ORG_ROLE_PRIORITY = (
        "super_admin", "admin", "org_admin",
        "project_admin", "project_member",
    )

    def _derive(user_obj):
        held = {n for (n,) in (
            db.query(RoleModel.name)
            .join(
                UserRoleAssignmentModel,
                UserRoleAssignmentModel.role_id == RoleModel.id,
            )
            .filter(UserRoleAssignmentModel.user_id == user_obj.id)
            .distinct().all()
        )}
        for tier in _ORG_ROLE_PRIORITY:
            if tier in held:
                return tier
        col = getattr(user_obj, "org_role", None)
        return col if col in _ORG_ROLE_PRIORITY else None

    project = (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .first()
    )
    if project is None:
        raise NotFoundError(f"Project {project_uuid} not found.")

    # (a) Users with a project-scoped role on this project.
    project_scoped_rows = (
        db.query(UserModel)
        .join(
            UserRoleAssignmentModel,
            UserRoleAssignmentModel.user_id == UserModel.id,
        )
        .join(
            RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id,
        )
        .filter(UserRoleAssignmentModel.project_id == project_uuid)
        .filter(UserModel.deleted_at.is_(None))
        .all()
    )

    # (b) Vendors that own this project → org_admin holders for those vendors.
    vendor_ids = [
        row[0] for row in
        db.query(ProjectVendorModel.vendor_id)
        .filter(ProjectVendorModel.project_id == project_uuid)
        .all()
    ]
    org_admin_rows: list = []
    if vendor_ids:
        org_admin_rows = (
            db.query(UserModel)
            .join(
                UserRoleAssignmentModel,
                UserRoleAssignmentModel.user_id == UserModel.id,
            )
            .join(
                RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id,
            )
            .filter(UserRoleAssignmentModel.organization_id.in_(vendor_ids))
            .filter(RoleModel.name == "org_admin")
            .filter(UserModel.deleted_at.is_(None))
            .all()
        )

    # Round 11b hotfix — exclude users who hold admin / super_admin in
    # any form (legacy user_roles OR global user_role_assignments).
    admin_tier_user_ids = {
        uid for (uid,) in (
            db.query(UserRoleAssignmentModel.user_id)
            .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
            .filter(RoleModel.name.in_(("admin", "super_admin")))
            .filter(UserRoleAssignmentModel.organization_id.is_(None))
            .filter(UserRoleAssignmentModel.project_id.is_(None))
            .distinct().all()
        )
    } | {
        uid for (uid,) in (
            db.query(UserRoleModel.user_id)
            .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
            .filter(RoleModel.name.in_(("admin", "super_admin")))
            .distinct().all()
        )
    }

    # De-dup by user id; project the round-9b orgRole projection.
    seen: Dict[str, Dict[str, Any]] = {}
    for u in list(project_scoped_rows) + list(org_admin_rows):
        if u.id in seen:
            continue
        if u.id in admin_tier_user_ids:
            continue
        seen[u.id] = {
            "id": u.id,
            "login": u.login,
            "email": u.email,
            "firstName": u.first_name,
            "lastName": u.last_name,
            "orgRole": _derive(u),
        }

    return BaseController.ok(data={
        "projectId": project_uuid,
        "projectName": project.name,
        "users": sorted(seen.values(), key=lambda x: (x["login"] or "")),
    })
