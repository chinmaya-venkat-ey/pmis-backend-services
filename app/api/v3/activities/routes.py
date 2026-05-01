"""Activities routes.

Create is split by (type, mode) into four dedicated endpoints. Each
schema carries only the fields that type needs, so Swagger shows a
focused body and callers can't accidentally send fields that belong to
a different type.

    POST /milestones/{id}/activities/standard/create
    POST /milestones/{id}/activities/resource/count/create
    POST /milestones/{id}/activities/resource/details/create
    POST /milestones/{id}/activities/transactional/create

Read / update / delete / restore stay single endpoints. The update path
still handles full type transitions (standard ↔ resource ↔ transactional)
because editing the existing activity doesn't fit a per-type endpoint.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
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


@activities_milestone_router.post(
    "/{milestone_id}/activities/standard/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a standard activity under milestone",
    status_code=201,
)
def create_standard(
    request: Request, milestone_id: str,
    data: StandardActivityCreateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.create_standard(request, milestone_id, data, db)


@activities_milestone_router.post(
    "/{milestone_id}/activities/resource/count/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a resource activity (count mode) under milestone",
    status_code=201,
)
def create_resource_count(
    request: Request, milestone_id: str,
    data: ResourceCountActivityCreateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.create_resource_count(request, milestone_id, data, db)


@activities_milestone_router.post(
    "/{milestone_id}/activities/resource/details/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a resource activity (details mode, full classification) under milestone",
    status_code=201,
)
def create_resource_details(
    request: Request, milestone_id: str,
    data: ResourceDetailsActivityCreateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.create_resource_details(request, milestone_id, data, db)


@activities_milestone_router.post(
    "/{milestone_id}/activities/transactional/create",
    dependencies=[require_permission(ACTIVITIES_CREATE)],
    summary="Create a transactional activity under milestone",
    status_code=201,
)
def create_transactional(
    request: Request, milestone_id: str,
    data: TransactionalActivityCreateRequest, db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return ActivityController.create_transactional(request, milestone_id, data, db)


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
