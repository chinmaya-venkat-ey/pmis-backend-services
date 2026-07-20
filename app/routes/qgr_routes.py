"""QGR CRUD routes — mounted under ``/api/v3/projects/{uuid}/qgr``.

Three endpoints (mirror the leave-policies pattern, but full CRUD since
QGR is effective-dated and needs history):

  * GET    /api/v3/projects/{uuid}/qgr
  * POST   /api/v3/projects/{uuid}/qgr
  * DELETE /api/v3/projects/{uuid}/qgr/{config_id}

Consumed by:
  * Contract-management NpqpService (via cross-schema SELECT — no HTTP hop).
  * FE settlement setup page.

RBAC:
  * GET    → ``projects:read`` scoped
  * POST   → ``projects:update:config`` (same as leave-policies)
  * DELETE → same
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.permissions import PROJECTS_READ, PROJECTS_UPDATE_CONFIG
from app.core.rbac import require_project_permission
from app.db import get_db
from app.schemas.qgr import (
    ProjectQgrConfigCreate,
    ProjectQgrConfigItem,
    ProjectQgrConfigList,
)
from app.services.qgr_service import QgrService


router = APIRouter(prefix="/projects", tags=["qgr"])


_QGR_ROW_EXAMPLE = {
    "id": "a32733a7-6235-4a19-878b-6875f3c05d14",
    "projectId": "60c67666-895f-4138-bd99-c907b571e933",
    "phase": "PHASE_1",
    "qgrAmountPerQuarter": "100000.00",
    "effectiveFrom": "2026-01-01",
    "effectiveUntil": None,
    "notes": "Initial contract QGR",
    "createdAt": "2026-07-20T09:00:28Z",
    "updatedAt": "2026-07-20T09:00:28Z",
}


@router.get(
    "/{project_uuid}/qgr",
    response_model=ProjectQgrConfigList,
    summary="List QGR rows for this project (history + active)",
    description=(
        "Returns every project_qgr_config row for the project, sorted by "
        "phase then effective_from DESC. NpqpService reads the row "
        "active on the settlement quarter's end date; historical rows "
        "let past quarters settle with the QGR that was actually in "
        "force at the time.\n\n"
        "Empty items[] when the project has no QGR configured (project "
        "will settle with QGR=0)."
    ),
    responses={200: {"content": {"application/json": {"example": {
        "projectId": "60c67666-895f-4138-bd99-c907b571e933",
        "items": [_QGR_ROW_EXAMPLE],
    }}}}},
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def list_project_qgr(
    project_uuid: str,
    db: Annotated[Session, Depends(get_db)],
):
    rows = QgrService(db).list_for_project(project_uuid)
    return ProjectQgrConfigList(
        project_id=project_uuid,
        items=[ProjectQgrConfigItem.model_validate(r) for r in rows],
    )


@router.post(
    "/{project_uuid}/qgr",
    response_model=ProjectQgrConfigItem,
    status_code=201,
    summary="Add a new effective-dated QGR row",
    description=(
        "Appends a new project_qgr_config row. To *change* QGR going "
        "forward, POST a new row with a later effective_from — the "
        "settlement service picks whichever row's window covers the "
        "quarter's end date. Duplicate (project_id, phase, "
        "effective_from) is refused by the unique constraint.\n\n"
        "Body accepts snake_case field names (`qgr_amount_per_quarter`, "
        "`effective_from`, `effective_until`). Response uses camelCase."
    ),
    responses={
        201: {"content": {"application/json": {"example": _QGR_ROW_EXAMPLE}}},
        409: {"description": "Duplicate (project, phase, effective_from)"},
        422: {"description": "effective_until earlier than effective_from"},
    },
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_CONFIG))],
)
def create_project_qgr(
    project_uuid: str,
    payload: ProjectQgrConfigCreate,
    db: Annotated[Session, Depends(get_db)],
):
    row = QgrService(db).create(
        project_id=project_uuid,
        phase=payload.phase,
        qgr_amount_per_quarter=payload.qgr_amount_per_quarter,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        notes=payload.notes,
    )
    return ProjectQgrConfigItem.model_validate(row)


@router.delete(
    "/{project_uuid}/qgr/{config_id}",
    status_code=204,
    summary="Delete one QGR row",
    description=(
        "Removes a project_qgr_config row. Use sparingly — past quarters "
        "that have already settled with this row will not be recomputed."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_CONFIG))],
)
def delete_project_qgr(
    project_uuid: str,
    config_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    QgrService(db).delete(project_id=project_uuid, config_id=config_id)
    return None
