"""Read-only catalog lookup routes served at /api/v3/{catalog}.

Project-svc exposes these for FE dropdown loading without the /master/ prefix,
matching the VM project service (port 8003). Writes remain in masters-svc.

Endpoints:
  GET  /api/v3/divisions
  GET  /api/v3/priorities
  GET  /api/v3/resource_types
  POST /api/v3/resource_types/create
  GET  /api/v3/project_status_transitions
"""
from __future__ import annotations

import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import require_authenticated
from app.db import get_db
from app.models._cross_schema import (
    Division,
    Priority,
    ProjectStatusTransition,
    ResourceType,
)
from app.schemas.catalog import (
    DivisionResponse,
    PriorityResponse,
    ProjectStatusTransitionResponse,
    ResourceTypeCreateRequest,
    ResourceTypeResponse,
)


router = APIRouter(tags=["catalog"])


@router.get(
    "/divisions",
    response_model=List[DivisionResponse],
    response_model_by_alias=True,
    summary="List divisions (catalog lookup)",
    dependencies=[Depends(require_authenticated())],
)
def list_divisions(
    db: Annotated[Session, Depends(get_db)],
    include_inactive: bool = Query(False),
) -> List[DivisionResponse]:
    stmt = select(Division)
    if not include_inactive:
        stmt = stmt.where(Division.active.is_(True))
    # requires_other=True ("Others") must always appear last (Bug #1).
    stmt = stmt.order_by(Division.requires_other.asc(), Division.label.asc())
    rows = db.execute(stmt).scalars().all()
    return [DivisionResponse.model_validate(r) for r in rows]


@router.get(
    "/priorities",
    response_model=List[PriorityResponse],
    summary="List priorities (catalog lookup)",
    dependencies=[Depends(require_authenticated())],
)
def list_priorities(
    db: Annotated[Session, Depends(get_db)],
    include_inactive: bool = Query(False),
) -> List[PriorityResponse]:
    stmt = select(Priority)
    if not include_inactive:
        stmt = stmt.where(Priority.active.is_(True))
    stmt = stmt.order_by(Priority.position.asc())
    rows = db.execute(stmt).scalars().all()
    # Bug #7: FE uses `name` for column display; return code ("P1/P2/P3") as name.
    return [
        PriorityResponse(
            id=r.id, code=r.code, name=r.code,
            description=r.description, position=r.position,
            is_builtin=r.is_builtin, active=r.active,
        )
        for r in rows
    ]


@router.get(
    "/resource_types",
    response_model=List[ResourceTypeResponse],
    summary="List resource types (catalog lookup)",
    dependencies=[Depends(require_authenticated())],
)
def list_resource_types(
    db: Annotated[Session, Depends(get_db)],
    include_inactive: bool = Query(False),
) -> List[ResourceTypeResponse]:
    stmt = select(ResourceType)
    if not include_inactive:
        stmt = stmt.where(ResourceType.active.is_(True))
    rows = db.execute(stmt).scalars().all()
    return [ResourceTypeResponse.model_validate(r) for r in rows]


@router.post(
    "/resource_types/create",
    response_model=ResourceTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resource type",
    dependencies=[Depends(require_authenticated())],
    responses={409: {"description": "Resource type code already exists"}},
)
def create_resource_type(
    payload: ResourceTypeCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ResourceTypeResponse:
    existing = db.execute(
        select(ResourceType).where(ResourceType.code == payload.code)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Resource type code already exists")
    row = ResourceType(
        id=str(uuid.uuid4()),
        code=payload.code,
        name=payload.name,
        active=payload.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ResourceTypeResponse.model_validate(row)


@router.get(
    "/project_status_transitions",
    response_model=List[ProjectStatusTransitionResponse],
    summary="List project status transitions (catalog lookup)",
    dependencies=[Depends(require_authenticated())],
)
def list_project_status_transitions(
    db: Annotated[Session, Depends(get_db)],
) -> List[ProjectStatusTransitionResponse]:
    rows = db.execute(
        select(ProjectStatusTransition).where(ProjectStatusTransition.active.is_(True))
    ).scalars().all()
    return [ProjectStatusTransitionResponse.model_validate(r) for r in rows]
