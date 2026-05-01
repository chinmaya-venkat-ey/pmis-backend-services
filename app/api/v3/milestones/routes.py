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
    status_code=201,
)
def create(
    request: Request,
    project_uuid: str,
    data: MilestoneCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return MilestoneController.create(request, project_uuid, data, db)


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
