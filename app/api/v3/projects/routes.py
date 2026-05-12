"""
Project routes - URL definitions with permission bindings.

All URL path parameters use ``project_uuid`` (the public handle). The
controller resolves UUID -> internal id.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import NotFoundError
from ....core.middleware.rbac import require_permission
from ....core.permissions import COMMENTS_CREATE, PROJECT_MEMBERS_READ
from ....core.response import format_error_response
from ....infrastructure.db.models.project import ProjectModel
from ....infrastructure.db.models.project_vendor import ProjectVendorModel
from ....infrastructure.db.models.role import RoleModel
from ....infrastructure.db.models.user import UserModel
from ....infrastructure.db.models.user_role import UserRoleModel
from ....infrastructure.db.models.user_role_assignment import (
    UserRoleAssignmentModel,
)
from ....infrastructure.db.session import get_db

from .._inline_attachments import dispatch_create, pre_validate_files
from ..comments.services import create_comment
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
    summary="Create project (JSON or multipart with optional file attachments)",
    description=(
        "Dual-mode dispatch: ``application/json`` keeps the legacy "
        "behaviour; ``multipart/form-data`` accepts the same project "
        "fields PLUS optional ``files[]`` for documents (project "
        "charter, RFP, scope notes etc.). Attached files land in the "
        "shared comments table with ``body=NULL`` and "
        "``target_kind=\"project\"`` — exposed back through "
        "``GET /projects/{id}/attachments``."
    ),
    status_code=201,
    # Route signature is ``Request`` (so we can dispatch on Content-Type),
    # which means FastAPI can't auto-generate the request-body OpenAPI
    # schema. Declare it explicitly so Swagger UI renders body input
    # fields for both shapes. JSON schema comes from the Pydantic model
    # so Swagger stays in sync with the validators.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": ProjectCreateRequest.model_json_schema(
                        by_alias=True,
                    ),
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {
                                "type": "string", "minLength": 1, "maxLength": 255,
                            },
                            "description": {
                                "type": "string", "maxLength": 5000,
                            },
                            "statusExplanation": {
                                "type": "string", "maxLength": 5000,
                            },
                            "parentId": {
                                "type": "string",
                                "description": "Parent project UUID (optional).",
                            },
                            "status": {
                                "type": "string",
                                "description": "Project lifecycle status (new/draft/published/closed).",
                            },
                            "owner": {
                                "type": "string",
                                "description": "Division code: tmd1 / tmd2 / others.",
                            },
                            "ownerOther": {
                                "type": "string",
                                "description": (
                                    "Required (non-empty) when ``owner == 'others'``. "
                                    "Omit / null for other owner values."
                                ),
                            },
                            "vendorIds": {
                                "type": "string",
                                "description": (
                                    "JSON-encoded array of vendor UUIDs or vendor codes "
                                    "(e.g. ``[\"VN-ACME-...\"]``). Multipart can't carry "
                                    "typed arrays natively so the FE JSON-encodes them."
                                ),
                            },
                            "startDate": {
                                "type": "string", "format": "date-time",
                                "description": "ISO 8601, e.g. 2026-07-01T00:00:00+05:30",
                            },
                            "endDate": {
                                "type": "string", "format": "date-time",
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": (
                                    "Optional file uploads. Each file is stored as a "
                                    "comment row with ``body=NULL`` and "
                                    "``target_kind=\"project\"``. Allowed extensions "
                                    "and per-file size cap apply. Disguised binaries "
                                    "(e.g. .exe renamed to .pdf) are rejected by the "
                                    "magic-byte content sniff."
                                ),
                            },
                        },
                    },
                },
            },
        },
    },
)
async def create_project(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=ProjectCreateRequest,
        json_handler=lambda req, db, data:
            ProjectController.create(req, data, db),
        multipart_handler=lambda req, db:
            ProjectController.create_multipart(req, db),
        json_args=(db,),
        multipart_args=(db,),
    )


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


# ---------------------------------------------------------------------------
# Project audit logs (doc 47)
# ---------------------------------------------------------------------------

@router.get(
    "/{project_uuid}/audit-logs",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="Project audit logs (doc 47)",
    description=(
        "Returns the recorded audit events for ``project_uuid`` — every "
        "state change, M/A/T/S subtree edit, vendor/member association, "
        "and dependency tweak that ``record_audit`` captured. Newest "
        "row first. Each entry carries the snapshotted ``actorLogin`` / "
        "``actorCode`` / ``actorRole`` at write time so the log row "
        "stays meaningful even if the source user / project rows later "
        "mutate. Project identity (``projectId`` / ``projectCode`` / "
        "``projectName`` / ``projectStatus`` / ``owner``) is hoisted to "
        "the top-level ``project`` block since every row in this "
        "collection is scoped to one project. Authorization: any "
        "caller with PROJECTS_READ."
    ),
)
def list_project_audit_logs(
    project_uuid: str,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)."),
    pageSize: int = Query(50, ge=1, le=200, description="Items per page (max 200)."),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from ....infrastructure.db.repositories.project_audit_log_repository import (
        ProjectAuditLogRepository,
    )

    project = (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .first()
    )
    if project is None:
        raise NotFoundError(f"Project {project_uuid} not found.")

    db_offset = (offset - 1) * pageSize
    rows, total = ProjectAuditLogRepository(db).list_for_project(
        project_id=project_uuid,
        offset=db_offset,
        limit=pageSize,
    )

    def _to_response(entry) -> Dict[str, Any]:
        d = entry.to_dict()
        # Per-entry payload — only the audit-event-specific fields.
        # Project identity (id / code / name / status / owner) is the
        # same for every row in this collection so it lives at the
        # top-level ``project`` key instead of being repeated.
        return {
            "id": d["id"],
            "actorId": d["actor_id"],
            "actorCode": d["actor_code"],
            "actorLogin": d["actor_login"],
            "actorRole": d["actor_role"],
            "action": d["action"],
            "before": d["before"],
            "after": d["after"],
            "createdAt": d["created_at"],
        }

    return BaseController.ok(data={
        "_type": "Collection",
        "_links": {
            "self": {
                "href": f"/api/v3/projects/{project_uuid}/audit-logs"
                        f"?offset={offset}&pageSize={pageSize}"
            },
        },
        "project": {
            "projectId": project.id,
            "projectCode": project.project_code,
            "projectName": project.name,
            "projectStatus": project.status,
            "owner": project.owner,
        },
        "total": total,
        "count": len(rows),
        "offset": offset,
        "pageSize": pageSize,
        "_embedded": {"elements": [_to_response(r) for r in rows]},
    })


# ---------------------------------------------------------------------------
# Project attachments (project-honest URL surface; storage is the
# shared comments table — see app/api/v3/comments/_target_helper.py
# for the polymorphism whitelist).
# ---------------------------------------------------------------------------

def _list_project_attachments_rows(db: Session, project_uuid: str) -> List[Dict[str, Any]]:
    """Slim attachment rows for the GET endpoint. Each entry is one
    file, carrying the parent comment row id (use it with DELETE
    ``/api/v3/comments/{id}`` to soft-delete the attachment)."""
    from ....infrastructure.db.models.comment import CommentModel
    rows = (
        db.query(CommentModel)
        .filter(CommentModel.target_kind == "project")
        .filter(CommentModel.target_id == project_uuid)
        .filter(CommentModel.deleted_at.is_(None))
        .order_by(CommentModel.created_at.asc())
        .all()
    )
    out: List[Dict[str, Any]] = []
    for c in rows:
        for att in (c.attachments or []):
            # JSON column persists camelCase keys (see
            # ``AttachmentInfo.to_dict``).
            out.append({
                "id": c.id,
                "filename": att.get("filename"),
                "url": att.get("url"),
                "mimeType": att.get("mimeType") or att.get("mime_type"),
                "sizeBytes": att.get("sizeBytes") or att.get("size_bytes"),
                "uploadedAt": att.get("uploadedAt") or att.get("uploaded_at"),
                "createdAt": c.created_at.isoformat() if c.created_at else None,
                "createdBy": c.author_user_id,
            })
    return out


@router.get(
    "/{project_uuid}/attachments",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="List attachments uploaded against this project",
)
def list_project_attachments(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .filter(ProjectModel.deleted_at.is_(None))
        .first()
    ) is None:
        raise NotFoundError(f"Project {project_uuid} not found.")
    items = _list_project_attachments_rows(db, project_uuid)
    return BaseController.ok(data={
        "_type": "Collection",
        "total": len(items),
        "count": len(items),
        "_embedded": {"elements": items},
    })


@router.post(
    "/{project_uuid}/attachments",
    dependencies=[require_permission(COMMENTS_CREATE)],
    summary="Upload more attachments to an existing project (multipart)",
    description=(
        "Multipart-only endpoint for adding files to a project after "
        "create. Accepts ``files[]`` repeated; no comment body — "
        "projects do not surface a comment-text field on this URL. "
        "Files land in the comments table with ``body=NULL`` and "
        "``target_kind=\"project\"`` for storage; the response carries "
        "the FE-facing flat attachment shape."
    ),
    status_code=201,
    # Render a file picker in Swagger UI rather than the auto-generated
    # contentMediaType variant (which Swagger 5.x falls back to a text
    # field for). Same pattern as POST /projects/create.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": (
                                    "One or more files to attach to the "
                                    "project. Repeated form key ``files``; "
                                    "Swagger UI's \"Add string item\" "
                                    "button adds another picker. Allowed "
                                    "extensions + per-file size cap apply; "
                                    "disguised binaries (e.g. .exe renamed "
                                    "to .pdf) are rejected by the magic-"
                                    "byte content sniff."
                                ),
                            },
                        },
                    },
                },
            },
        },
    },
)
async def upload_project_attachments(
    request: Request,
    project_uuid: str,
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .filter(ProjectModel.deleted_at.is_(None))
        .first()
    ) is None:
        raise NotFoundError(f"Project {project_uuid} not found.")
    files = files or []
    if not files:
        return BaseController.error(
            format_error_response(
                error_type="validation_error",
                message="At least one file is required.",
            ),
            status=422,
        )
    # Pre-validate (size + extension + magic-byte content sniff).
    file_err = pre_validate_files(files)
    if file_err is not None:
        return BaseController.error(
            format_error_response(
                error_type=file_err["error_type"],
                message=file_err["message"],
                details=file_err["details"],
            ),
            status=422,
        )
    current_user_id = getattr(request.state, "user_id", None)
    result = create_comment(
        db=db,
        target_kind="project",
        target_id=project_uuid,
        body=None,
        files=files,
        author_user_id=current_user_id,
    )
    if not result.is_success():
        return BaseController.error(
            format_error_response(
                error_type=result.error_type or "internal_error",
                message=result.error or "Failed to attach files.",
                details=result.details,
            ),
            status=422,
        )
    # Emit the slim attachment shape for these freshly-uploaded rows
    # only (caller wants "what just got created", not the full project
    # attachment listing).
    comment = result.data
    new_rows: List[Dict[str, Any]] = []
    for att in (comment.attachments or []):
        new_rows.append({
            "id": comment.id,
            "filename": att.filename if hasattr(att, "filename") else att.get("filename"),
            "url": att.url if hasattr(att, "url") else att.get("url"),
            "mimeType": att.mime_type if hasattr(att, "mime_type") else att.get("mime_type"),
            "sizeBytes": att.size_bytes if hasattr(att, "size_bytes") else att.get("size_bytes"),
            "uploadedAt": (
                att.uploaded_at.isoformat()
                if hasattr(att, "uploaded_at") and att.uploaded_at
                else att.get("uploaded_at") if isinstance(att, dict) else None
            ),
            "createdAt": comment.created_at.isoformat() if comment.created_at else None,
            "createdBy": comment.author_user_id,
        })
    return BaseController.created(data={
        "_type": "Collection",
        "total": len(new_rows),
        "count": len(new_rows),
        "_embedded": {"elements": new_rows},
    })


# ---------------------------------------------------------------------------
# Discussion feed — unified view of every comment row tied to the project
# tree (the project itself + every milestone / activity / task / subtask
# under it). Each row carries body (optional) AND attachments JSON list
# (optional), so the response captures both written discussion and
# shared files in one collated, time-ordered feed.
# ---------------------------------------------------------------------------

@router.get(
    "/{project_uuid}/discussion-feed",
    dependencies=[require_permission(PROJECTS_READ)],
    summary="Unified discussion + attachments feed for the project tree",
    description=(
        "Returns every comment row attached to this project OR any of "
        "its descendants (milestones / activities / tasks / subtasks) "
        "in a single flat, newest-first, paginated feed. Each row "
        "carries ``body`` (optional comment text) AND ``attachments`` "
        "(JSON list of file metadata) so a single response captures "
        "both written discussion and shared files. Each row also "
        "carries ``targetKind`` / ``targetId`` / ``targetName`` so the "
        "FE can render which entity in the tree the row belongs to. "
        "Soft-deleted rows (and soft-deleted target entities) are "
        "filtered out."
    ),
)
def list_project_discussion_feed(
    project_uuid: str,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)."),
    pageSize: int = Query(50, ge=1, le=200, description="Items per page (max 200)."),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    from sqlalchemy import and_, or_

    from ....infrastructure.db.models.activity import ActivityModel
    from ....infrastructure.db.models.comment import CommentModel
    from ....infrastructure.db.models.milestone import MilestoneModel
    from ....infrastructure.db.models.subtask import SubtaskModel
    from ....infrastructure.db.models.task import TaskModel

    project = (
        db.query(ProjectModel)
        .filter(ProjectModel.id == project_uuid)
        .filter(ProjectModel.deleted_at.is_(None))
        .first()
    )
    if project is None:
        raise NotFoundError(f"Project {project_uuid} not found.")

    # Walk the tree once — get the live ids for every kind. Each
    # entity model carries a denormalized ``project_id`` column for
    # exactly this kind of query, so each scan is one indexed lookup.
    milestone_id_to_name: Dict[str, str] = {
        mid: mname for (mid, mname) in (
            db.query(MilestoneModel.id, MilestoneModel.name)
            .filter(MilestoneModel.project_id == project_uuid)
            .filter(MilestoneModel.deleted_at.is_(None))
            .all()
        )
    }
    activity_id_to_name: Dict[str, str] = {
        aid: aname for (aid, aname) in (
            db.query(ActivityModel.id, ActivityModel.name)
            .filter(ActivityModel.project_id == project_uuid)
            .filter(ActivityModel.deleted_at.is_(None))
            .all()
        )
    }
    task_id_to_name: Dict[str, str] = {
        tid: tname for (tid, tname) in (
            db.query(TaskModel.id, TaskModel.name)
            .filter(TaskModel.project_id == project_uuid)
            .filter(TaskModel.deleted_at.is_(None))
            .all()
        )
    }
    subtask_id_to_name: Dict[str, str] = {
        sid: sname for (sid, sname) in (
            db.query(SubtaskModel.id, SubtaskModel.name)
            .filter(SubtaskModel.project_id == project_uuid)
            .filter(SubtaskModel.deleted_at.is_(None))
            .all()
        )
    }

    clauses = [
        and_(
            CommentModel.target_kind == "project",
            CommentModel.target_id == project_uuid,
        ),
    ]
    if milestone_id_to_name:
        clauses.append(and_(
            CommentModel.target_kind == "milestone",
            CommentModel.target_id.in_(milestone_id_to_name.keys()),
        ))
    if activity_id_to_name:
        clauses.append(and_(
            CommentModel.target_kind == "activity",
            CommentModel.target_id.in_(activity_id_to_name.keys()),
        ))
    if task_id_to_name:
        clauses.append(and_(
            CommentModel.target_kind == "task",
            CommentModel.target_id.in_(task_id_to_name.keys()),
        ))
    if subtask_id_to_name:
        clauses.append(and_(
            CommentModel.target_kind == "subtask",
            CommentModel.target_id.in_(subtask_id_to_name.keys()),
        ))

    base_q = (
        db.query(CommentModel)
        .filter(or_(*clauses))
        .filter(CommentModel.deleted_at.is_(None))
    )
    total = base_q.count()
    db_offset = (offset - 1) * pageSize
    rows = (
        # Tie-break on ``id`` so pagination is stable when multiple
        # comments share a ``created_at`` (common in same-second
        # bursts; SQLite truncates fractional seconds in tests).
        base_q.order_by(CommentModel.created_at.desc(), CommentModel.id.desc())
        .offset(db_offset)
        .limit(pageSize)
        .all()
    )

    name_resolvers: Dict[str, Dict[str, str]] = {
        "project": {project_uuid: project.name},
        "milestone": milestone_id_to_name,
        "activity": activity_id_to_name,
        "task": task_id_to_name,
        "subtask": subtask_id_to_name,
    }

    # Bulk-resolve author logins so each row can carry the username
    # next to the raw ``createdBy`` UUID. Single query per page.
    # Soft-deleted users still resolve so historical comments don't
    # render with a missing login. Comments with NULL author (system
    # inserts) map to None.
    author_ids = {c.author_user_id for c in rows if c.author_user_id}
    author_login_by_id: Dict[str, str] = {}
    if author_ids:
        for uid, login in (
            db.query(UserModel.id, UserModel.login)
            .filter(UserModel.id.in_(author_ids))
            .all()
        ):
            author_login_by_id[uid] = login

    def _shape(c) -> Dict[str, Any]:
        return {
            "id": c.id,
            "targetKind": c.target_kind,
            "targetId": c.target_id,
            "targetName": name_resolvers.get(c.target_kind, {}).get(c.target_id),
            "body": c.body,
            "attachments": c.attachments or [],
            "createdAt": c.created_at.isoformat() if c.created_at else None,
            "createdBy": c.author_user_id,
            "createdByLogin": author_login_by_id.get(c.author_user_id),
        }

    return BaseController.ok(data={
        "_type": "Collection",
        "_links": {
            "self": {
                "href": (
                    f"/api/v3/projects/{project_uuid}/discussion-feed"
                    f"?offset={offset}&pageSize={pageSize}"
                ),
            },
        },
        "project": {"id": project_uuid, "name": project.name},
        "total": total,
        "count": len(rows),
        "offset": offset,
        "pageSize": pageSize,
        "_embedded": {"elements": [_shape(c) for c in rows]},
    })
