"""Finance routes — mounted under ``/api/v3/projects/{uuid}/finance``.

Two endpoints (Doc-finance):
  - GET   /api/v3/projects/{uuid}/finance  — full finance summary
  - PATCH /api/v3/projects/{uuid}/finance  — update finance fields

RBAC:
  - GET   → ``projects:read`` scoped (admin bypass).
  - PATCH → ``projects:update:finance`` scoped (org_admin / project_admin
            + admin / super_admin via admin-bypass). Service layer adds
            the publish-lock (409 once status='published').
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request

from app.controllers.finance_controller import FinanceController
from app.core.permissions import PROJECTS_READ, PROJECTS_UPDATE_FINANCE
from app.core.rbac import require_project_permission
from app.dependencies import (
    get_finance_controller,
    get_optional_current_user_id,
)
from app.schemas.finance import FinanceSummaryResponse, FinanceUpdateRequest


router = APIRouter(prefix="/projects", tags=["finance"])


@router.get(
    "/{project_uuid}/finance",
    response_model=FinanceSummaryResponse,
    summary="Get the project's finance summary (TPV, CCN cap/used, items)",
    description=(
        "Returns the full finance view for the project: contract values "
        "(excl/incl tax + tax %), CCN cap amount + utilisation, headroom, "
        "effective contract value, and the list of every CCN-categorized "
        "milestone / activity. ``ccnUsedPercent`` / ``ccnHeadroom`` are "
        "``null`` when Total Project Value is 0 (cap dormant)."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_READ))],
)
def get_finance(
    project_uuid: str,
    controller: Annotated[FinanceController, Depends(get_finance_controller)],
):
    return controller.get(project_uuid)


@router.patch(
    "/{project_uuid}/finance",
    response_model=FinanceSummaryResponse,
    summary="Update contract finance fields (publish-locked)",
    description=(
        "Partial update of the project's contract finance fields. All "
        "three fields are optional; only the ones sent in the body are "
        "touched. Once the project is published the fields are locked: "
        "any update attempt returns 409 ``conflict`` (\"Final onboarding\")."
    ),
    dependencies=[Depends(require_project_permission(PROJECTS_UPDATE_FINANCE))],
)
def update_finance(
    project_uuid: str,
    payload: FinanceUpdateRequest,
    request: Request,
    controller: Annotated[FinanceController, Depends(get_finance_controller)],
    caller_user_id: Annotated[Optional[str], Depends(get_optional_current_user_id)],
):
    return controller.update(
        project_uuid, payload, caller_user_id=caller_user_id,
    )
