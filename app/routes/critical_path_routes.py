"""Critical Path Analysis routes.

GET  /api/v3/projects/{project_id}/critical-path/dependencies
  Returns the dependency table: every activity with its predecessor list,
  days_needed, days_delayed, effective_duration, and status.
  Gated by projects:read.

POST /api/v3/projects/{project_id}/critical-path/analysis
  Runs the CPM algorithm and returns:
    - metadata (total_project_days, activities_on_critical_path, ...)
    - critical_path  (ordered list of display codes)
    - activity_schedule  (ES, EF, LS, LF, slack, on_critical_path per activity)
    - flow_diagram  (nodes + edges for the FE graph renderer)
  Accepts an optional body with per-activity duration overrides for
  what-if scenario planning. Gated by projects:read.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends

from app.controllers.critical_path_controller import CriticalPathController
from app.core.permissions import PROJECTS_READ
from app.core.rbac import require_permission, require_project_permission
from app.dependencies import get_critical_path_controller
from app.schemas.critical_path import CpaAnalysisRequest


router = APIRouter(
    prefix="/projects",
    tags=["critical-path"],
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)


@router.get(
    "/{project_id}/critical-path/dependencies",
    summary="Dependency table for critical path analysis",
    description=(
        "Returns every live activity under the project with its predecessor list, "
        "days_needed (planned end − planned start), days_delayed (actual_end − planned_end), "
        "effective_duration, and current status. Read-only, no DB writes."
    ),
)
def get_dependencies(
    project_id: str,
    controller: Annotated[CriticalPathController, Depends(get_critical_path_controller)],
) -> Dict[str, Any]:
    return controller.dependencies(project_id)


@router.post(
    "/{project_id}/critical-path/analysis",
    summary="Full CPM critical path analysis",
    description=(
        "Runs the Critical Path Method algorithm on all live activities under the "
        "project. Returns the critical path (ordered display codes), full activity "
        "schedule (ES/EF/LS/LF/slack/on_critical_path), flow diagram nodes and edges, "
        "and project metadata. "
        "The optional request body accepts per-activity duration overrides "
        "(days_needed and/or days_delayed) for what-if scenario planning. "
        "Read-only, no DB writes."
    ),
)
def get_analysis(
    project_id: str,
    controller: Annotated[CriticalPathController, Depends(get_critical_path_controller)],
    body: Optional[CpaAnalysisRequest] = None,
) -> Dict[str, Any]:
    overrides = body.overrides if body else None
    return controller.analysis(project_id, overrides=overrides)
