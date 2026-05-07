"""Activities routes.

Doc 38: the four legacy type-specific create endpoints (standard /
resource-count / resource-details / transactional) collapse to a
single ``POST /milestones/{milestone_id}/activities/create``. ``type``,
``resourceMode``, ``resourceCount``, ``resource`` are no longer accepted
on create. Status / dependsOn / actual dates / resource block remain
on PATCH for back-compat with legacy rows.
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
    ActivityCreateRequest,
    ActivityListQuery,
    ActivityUpdateRequest,
)


activities_milestone_router = APIRouter(prefix="/milestones", tags=["activities"])
activities_router = APIRouter(prefix="/activities", tags=["activities"])


# Doc 38 multipart-form spec — only the doc-38 minimal fields.
def _activity_multipart_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 255},
            "description": {"type": "string", "maxLength": 5000},
            "startDate": {"type": "string", "format": "date-time"},
            "endDate": {"type": "string", "format": "date-time"},
            "position": {"type": "integer", "minimum": 0},
            "ownerDivision": {"type": "string", "maxLength": 32},
            # Doc 39: keyword preserved (singular), datatype is now a list
            # of division codes. Send as JSON-encoded array in multipart
            # (the parser parses it via _ACTIVITY_ARRAY_KEYS).
            "concernedDivision": {
                "type": "string",
                "description": "JSON-encoded list of division codes.",
            },
            "vendorId": {"type": "string", "maxLength": 36},
            "body": {
                "type": "string",
                "description": "Optional comment text saved with the activity.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string", "format": "binary"},
                "description": "Optional file uploads attached to the activity comment.",
            },
        },
        # Doc 39: ownerDivision / vendorId / concernedDivision are mandatory on create.
        "required": [
            "name", "startDate", "endDate",
            "ownerDivision", "vendorId", "concernedDivision",
        ],
    }


def _activity_openapi_extra() -> Dict[str, Any]:
    # Inline the JSON schema (rather than referencing
    # #/components/schemas/ActivityCreateRequest, which never gets
    # registered because this route uses the dispatcher pattern and
    # doesn't take ActivityCreateRequest as a typed parameter — FastAPI
    # only auto-registers schemas reachable from a typed handler arg).
    # Inlining is what tasks/subtasks do; produces a fully expanded
    # JSON-Schema in Swagger so the FE sees every field + alias + type.
    return {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": ActivityCreateRequest.model_json_schema(by_alias=True),
                },
                "multipart/form-data": {"schema": _activity_multipart_schema()},
            },
        },
    }


@activities_milestone_router.post(
    "/{milestone_id}/activities/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create an activity under a milestone (doc 38)",
    description=(
        "Create an activity. Accepts EITHER ``application/json`` "
        "(legacy) OR ``multipart/form-data`` (doc 30 — same fields plus "
        "optional ``body`` (comment text) and ``files`` (uploads)).\n\n"
        "Doc 38: type / resource fields are no longer accepted here. "
        "Set ``status`` / ``dependsOn`` / ``actualStartDate`` / "
        "``actualEndDate`` via PATCH after the row exists."
    ),
    status_code=201,
    openapi_extra=_activity_openapi_extra(),
)
async def create_activity_route(
    request: Request, milestone_id: str, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return await dispatch_create(
        request,
        schema_cls=ActivityCreateRequest,
        json_handler=lambda req, milestone_id, db, data:
            ActivityController.create(req, milestone_id, data, db),
        multipart_handler=lambda req, milestone_id, db:
            ActivityController.create_multipart(req, milestone_id, db),
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
    summary="Update activity",
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
