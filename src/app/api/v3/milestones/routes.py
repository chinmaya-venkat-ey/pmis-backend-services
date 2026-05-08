"""Milestones routes.

Two routers because milestones have a two-path API surface:
  - project-scoped: POST/GET under /projects/{project_id}/milestones
  - id-scoped:      GET/PATCH/DELETE/restore under /milestones/{id}
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .._inline_attachments import dispatch_create
from .controller import MilestoneController
from .permissions import (
    MILESTONES_CREATE, MILESTONES_READ, MILESTONES_UPDATE,
    MILESTONES_DELETE, MILESTONES_RESTORE,
)
from .schemas import MilestoneCreateRequest, MilestoneUpdateRequest, MilestoneListQuery


# Project-scoped routes -- mounted under /api/v3/projects
milestones_project_router = APIRouter(prefix="/projects", tags=["milestones"])

# Id-scoped routes -- mounted under /api/v3/milestones
milestones_router = APIRouter(prefix="/milestones", tags=["milestones"])


@milestones_project_router.post(
    "/{project_uuid}/milestones/create",
    dependencies=[require_permission(MILESTONES_CREATE)],
    summary="Create milestone under project",
    description=(
        "Create a milestone. Accepts EITHER ``application/json`` (legacy "
        "shape — milestone fields only) OR ``multipart/form-data`` (doc 30 — "
        "milestone fields as form fields, plus optional ``body`` (comment "
        "text) and ``files`` (file uploads). When attachments are present, "
        "the milestone + comment + attachments are persisted in the same "
        "request. Array-typed fields (``dependsOn``, ``vendors``) are "
        "JSON-encoded strings inside multipart."
    ),
    status_code=201,
    # Doc 30: route signature is ``Request`` (so we can dispatch on
    # Content-Type), which means FastAPI can't auto-generate the
    # request-body OpenAPI schema. We declare it explicitly here so
    # Swagger UI renders body input fields for both shapes. The JSON
    # schema is generated from the Pydantic model directly to keep
    # Swagger in sync with the validators (MilestoneCreateRequest is
    # the same source of truth for both paths).
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": MilestoneCreateRequest.model_json_schema(
                        by_alias=True,
                    ),
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["name", "startDate", "endDate"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1, "maxLength": 255},
                            "description": {"type": "string", "maxLength": 5000},
                            "startDate": {
                                "type": "string", "format": "date-time",
                                "description": "ISO 8601, e.g. 2026-05-04T00:00:00+05:30",
                            },
                            "endDate": {"type": "string", "format": "date-time"},
                            "position": {"type": "integer", "minimum": 0},
                            "status": {
                                "type": "string",
                                "description": "One of: not_completed, completed",
                            },
                            "dependsOn": {
                                "type": "string",
                                "description": (
                                    "JSON-encoded array of milestone UUIDs or "
                                    "labels (e.g. ``[\"M2\"]``). Multipart can't "
                                    "carry typed arrays natively, so the FE "
                                    "JSON-encodes them as a string."
                                ),
                            },
                            "vendors": {
                                "type": "string",
                                "description": (
                                    "JSON-encoded array of vendor UUIDs or "
                                    "vendor codes (e.g. ``[\"VN-ACME-...\"]``)."
                                ),
                            },
                            "body": {
                                "type": "string",
                                "description": (
                                    "Optional comment text. If supplied, a "
                                    "comment row is created against the new "
                                    "milestone, and any uploaded files are "
                                    "bound to that comment."
                                ),
                            },
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": (
                                    "Optional file uploads. With ``body`` → "
                                    "bound to the comment. Without ``body`` → "
                                    "standalone attachments on the milestone."
                                ),
                            },
                        },
                    },
                },
            },
        },
    },
)
async def create(
    request: Request,
    project_uuid: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Doc 30 dual-mode dispatch.

    * ``application/json``       → existing path, no inline attachments
    * ``multipart/form-data``    → milestone + optional comment / files

    Both paths share the same ``MilestoneCreateRequest`` Pydantic
    validators (and therefore the same error shapes) — only the parser
    differs. The shared helper handles content-type sniffing,
    JSON-decode-error plumbing, and the Pydantic-to-422 conversion.
    """
    return await dispatch_create(
        request,
        schema_cls=MilestoneCreateRequest,
        json_handler=lambda req, project_uuid, db, data:
            MilestoneController.create(req, project_uuid, data, db),
        multipart_handler=lambda req, project_uuid, db:
            MilestoneController.create_multipart(req, project_uuid, db),
        json_args=(project_uuid, db),
        multipart_args=(project_uuid, db),
    )


@milestones_project_router.get(
    "/{project_uuid}/milestones",
    dependencies=[require_permission(MILESTONES_READ)],
    summary="List milestones under project",
)
def list_(
    request: Request,
    project_uuid: str,
    offset: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    includeDeleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.list(
        request, project_uuid,
        MilestoneListQuery(offset=offset, pageSize=pageSize, includeDeleted=includeDeleted),
        db,
    )


@milestones_router.get(
    "/{milestone_id}",
    dependencies=[require_permission(MILESTONES_READ)],
    summary="Get milestone by id",
)
def get(
    request: Request,
    milestone_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.get(request, milestone_id, db)


@milestones_router.patch(
    "/{milestone_id}",
    dependencies=[require_permission(MILESTONES_UPDATE)],
    summary="Update milestone",
)
def update(
    request: Request,
    milestone_id: str,
    data: MilestoneUpdateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.update(request, milestone_id, data, db)


@milestones_router.delete(
    "/{milestone_id}",
    dependencies=[require_permission(MILESTONES_DELETE)],
    summary="Soft-delete milestone (cascades to descendants)",
)
def delete(
    request: Request,
    milestone_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.delete(request, milestone_id, db)


@milestones_router.post(
    "/{milestone_id}/restore",
    dependencies=[require_permission(MILESTONES_RESTORE)],
    summary="Restore a soft-deleted milestone (admin)",
)
def restore(
    request: Request,
    milestone_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.restore(request, milestone_id, db)
