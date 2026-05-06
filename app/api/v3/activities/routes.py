"""Activities routes.

Create is split by (type, mode) into four dedicated endpoints. Each
schema carries only the fields that type needs, so Swagger shows a
focused body and callers can't accidentally send fields that belong to
a different type.

    POST /milestones/{id}/activities/standard/create
    POST /milestones/{id}/activities/resource/count/create
    POST /milestones/{id}/activities/resource/details/create
    POST /milestones/{id}/activities/transactional/create

Each is now dual-mode: ``application/json`` (legacy) or
``multipart/form-data`` (doc 30 — fields + optional ``body``/``files``).

Read / update / delete / restore stay single endpoints. The update path
still handles full type transitions (standard ↔ resource ↔ transactional)
because editing the existing activity doesn't fit a per-type endpoint.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .._inline_attachments import dispatch_create
from .controller import ActivityController
from .permissions import (
    ACTIVITIES_CREATE, ACTIVITIES_READ, ACTIVITIES_UPDATE,
    ACTIVITIES_DELETE, ACTIVITIES_RESTORE,
)
from .schemas import (
    ActivityUpdateRequest,
    ActivityListQuery,
    ResourceCountActivityCreateRequest,
    ResourceDetailsActivityCreateRequest,
    StandardActivityCreateRequest,
    TransactionalActivityCreateRequest,
)


activities_milestone_router = APIRouter(prefix="/milestones", tags=["activities"])
activities_router = APIRouter(prefix="/activities", tags=["activities"])


# Doc 30: shared multipart-body schema fragment for activity creates.
# Reused across the four create endpoints; each one extends it with the
# variant-specific fields. Documented for Swagger so the user sees both
# JSON and multipart options.
def _activity_multipart_schema_base() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["name", "startDate", "endDate"],
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string", "maxLength": 5000},
            "startDate": {"type": "string", "format": "date-time"},
            "endDate": {"type": "string", "format": "date-time"},
            "actualStartDate": {"type": "string", "format": "date-time"},
            "actualEndDate": {"type": "string", "format": "date-time"},
            "position": {"type": "integer", "minimum": 0},
            "status": {"type": "string"},
            "dependsOn": {
                "type": "string",
                "description": "JSON-encoded array of activity UUIDs/labels.",
            },
            "body": {
                "type": "string",
                "description": "Optional comment text. With files → bound to comment.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string", "format": "binary"},
                "description": (
                    "Optional file uploads. With ``body`` → bound to the "
                    "comment. Without ``body`` → standalone attachments."
                ),
            },
        },
    }


def _activity_openapi_extra(
    json_schema_cls,
    extra_props: Dict[str, Any] = None,
    extra_required: tuple = (),
) -> Dict[str, Any]:
    multipart_schema = _activity_multipart_schema_base()
    if extra_props:
        multipart_schema["properties"].update(extra_props)
    if extra_required:
        multipart_schema["required"] = list(multipart_schema["required"]) + list(extra_required)
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": json_schema_cls.model_json_schema(by_alias=True),
                },
                "multipart/form-data": {"schema": multipart_schema},
            },
        },
    }


@activities_milestone_router.post(
    "/{milestone_id}/activities/standard/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a standard activity under milestone",
    description=(
        "Create a standard activity. Accepts EITHER ``application/json`` "
        "(legacy) OR ``multipart/form-data`` (doc 30 — same fields plus "
        "optional ``body`` (comment text) and ``files`` (uploads))."
    ),
    status_code=201,
    openapi_extra=_activity_openapi_extra(StandardActivityCreateRequest),
)
async def create_standard(
    request: Request, milestone_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=StandardActivityCreateRequest,
        json_handler=lambda req, milestone_id, db, data:
            ActivityController.create_standard(req, milestone_id, data, db),
        multipart_handler=lambda req, milestone_id, db:
            ActivityController.create_standard_multipart(req, milestone_id, db),
        json_args=(milestone_id, db),
        multipart_args=(milestone_id, db),
    )


@activities_milestone_router.post(
    "/{milestone_id}/activities/resource/count/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a resource activity (count mode) under milestone",
    description=(
        "Create a resource/count activity. Accepts JSON or multipart "
        "(doc 30). ``resourceCount`` is required."
    ),
    status_code=201,
    openapi_extra=_activity_openapi_extra(
        ResourceCountActivityCreateRequest,
        extra_props={"resourceCount": {"type": "integer", "minimum": 1}},
        extra_required=("resourceCount",),
    ),
)
async def create_resource_count(
    request: Request, milestone_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=ResourceCountActivityCreateRequest,
        json_handler=lambda req, milestone_id, db, data:
            ActivityController.create_resource_count(req, milestone_id, data, db),
        multipart_handler=lambda req, milestone_id, db:
            ActivityController.create_resource_count_multipart(req, milestone_id, db),
        json_args=(milestone_id, db),
        multipart_args=(milestone_id, db),
    )


@activities_milestone_router.post(
    "/{milestone_id}/activities/resource/details/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a resource activity (details mode, full classification) under milestone",
    description=(
        "Create a resource/details activity. Accepts JSON or multipart "
        "(doc 30). The ``resource`` block (with typeOfResourceId + division "
        "+ resource fields) is JSON-encoded as a string in multipart since "
        "multipart can't carry typed nested objects."
    ),
    status_code=201,
    openapi_extra=_activity_openapi_extra(
        ResourceDetailsActivityCreateRequest,
        extra_props={
            "resource": {
                "type": "string",
                "description": (
                    "JSON-encoded object: {resourceName, typeOfResourceId, "
                    "division, ...optional fields}. Required fields per the "
                    "JSON schema apply identically."
                ),
            },
        },
        extra_required=("resource",),
    ),
)
async def create_resource_details(
    request: Request, milestone_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=ResourceDetailsActivityCreateRequest,
        json_handler=lambda req, milestone_id, db, data:
            ActivityController.create_resource_details(req, milestone_id, data, db),
        multipart_handler=lambda req, milestone_id, db:
            ActivityController.create_resource_details_multipart(req, milestone_id, db),
        json_args=(milestone_id, db),
        multipart_args=(milestone_id, db),
    )


@activities_milestone_router.post(
    "/{milestone_id}/activities/transactional/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a transactional activity under milestone",
    description=(
        "Create a transactional activity. Accepts JSON or multipart (doc 30)."
    ),
    status_code=201,
    openapi_extra=_activity_openapi_extra(TransactionalActivityCreateRequest),
)
async def create_transactional(
    request: Request, milestone_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=TransactionalActivityCreateRequest,
        json_handler=lambda req, milestone_id, db, data:
            ActivityController.create_transactional(req, milestone_id, data, db),
        multipart_handler=lambda req, milestone_id, db:
            ActivityController.create_transactional_multipart(req, milestone_id, db),
        json_args=(milestone_id, db),
        multipart_args=(milestone_id, db),
    )


@activities_milestone_router.get(
    "/{milestone_id}/activities",
    dependencies=[require_permission(ACTIVITIES_READ)],
    summary="List activities under milestone",
)
def list_(
    request: Request, milestone_id: str,
    offset: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
    includeDeleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.list(
        request, milestone_id,
        ActivityListQuery(offset=offset, pageSize=pageSize, includeDeleted=includeDeleted),
        db,
    )


@activities_router.get(
    "/{activity_id}",
    dependencies=[require_permission(ACTIVITIES_READ)],
    summary="Get activity by id",
)
def get(request: Request, activity_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return ActivityController.get(request, activity_id, db)


@activities_router.patch(
    "/{activity_id}",
    dependencies=[require_permission(ACTIVITIES_UPDATE)],
    summary="Update activity (handles type transitions + resource upsert)",
)
def update(
    request: Request, activity_id: str,
    data: ActivityUpdateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.update(request, activity_id, data, db)


@activities_router.delete(
    "/{activity_id}",
    dependencies=[require_permission(ACTIVITIES_DELETE)],
    summary="Soft-delete activity (cascades)",
)
def delete(request: Request, activity_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return ActivityController.delete(request, activity_id, db)


@activities_router.post(
    "/{activity_id}/restore",
    dependencies=[require_permission(ACTIVITIES_RESTORE)],
    summary="Restore a soft-deleted activity (admin)",
)
def restore(request: Request, activity_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return ActivityController.restore(request, activity_id, db)
