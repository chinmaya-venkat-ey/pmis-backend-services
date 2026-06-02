"""Tree route — single GET endpoint at ``/project/projects/{uuid}/tree``.

Returns the full M/A/T/S tree in one call, with resource sidecars
inlined and per-node ``scheduleStatus`` / ``daysDelayed`` derived from
plan vs. actual dates.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, Query

from app.controllers.tree_controller import TreeController
from app.core.permissions import PROJECTS_READ
from app.core.rbac import require_project_permission
from app.dependencies import get_tree_controller


router = APIRouter(prefix="/projects", tags=["tree"])


@router.get(
    "/{project_uuid}/tree",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
    summary="Full M/A/T/S tree under a project",
    description=(
        "Single payload: milestones → activities → tasks → subtasks "
        "(arbitrary nesting), with resource sidecars inlined for "
        "resource-type entities. Soft-deleted rows are filtered by "
        "default; pass ``includeDeleted=true`` to include them."
    ),
)
def get_project_tree(
    project_uuid: str,
    controller: Annotated[TreeController, Depends(get_tree_controller)],
    include_deleted: bool = Query(False, alias="includeDeleted"),
) -> Dict[str, Any]:
    return controller.get_tree(project_uuid, include_deleted=include_deleted)
