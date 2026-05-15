"""Tree route — single GET endpoint at
``/project/projects/{project_uuid}/tree/get``.

Gated by ``require_project_permission(PROJECTS_READ)`` — the caller must
hold ``projects:read`` either globally or scoped to the given project.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from app.controllers.tree_controller import TreeController
from app.core.permissions import PROJECTS_READ
from app.core.rbac import require_project_permission
from app.dependencies import get_tree_controller


router = APIRouter(prefix="/projects", tags=["tree"])


@router.get(
    "/{project_uuid}/tree/get",
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
    summary="Full M/A/T/S tree under a project",
    description=(
        "Returns the full project tree in one call: milestones → "
        "activities → tasks → subtasks, with resource details inlined "
        "for resource-type entities. Soft-deleted rows are filtered by "
        "default; pass `includeDeleted=true` to include them (admin-only "
        "in practice)."
    ),
)
def get_project_tree(
    project_uuid: str,
    includeDeleted: bool = Query(False),
    controller: TreeController = Depends(get_tree_controller),
) -> Dict[str, Any]:
    return controller.get_tree(project_uuid, include_deleted=includeDeleted)
