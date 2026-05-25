"""Dashboard routes — 6 GET endpoints under ``/project/dashboard/*``.

Every endpoint is gated by ``require_permission(PROJECTS_READ_ALL)`` at
the router level — anonymous callers get 401, callers without
``projects:read_all`` get 403. ``projects:read_all`` is the admin-tier
permission code in PMIS practice, so this is effectively admin-only.

Query params are camelCase (``delayMinDays``, ``pageSize``, ``vendorId``,
``milestoneId``, ``minDelay``) to match the monolith's wire contract —
the FE already consumes these names.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.controllers.dashboard_controller import DashboardController
from app.core.permissions import PROJECTS_READ_ALL
from app.core.rbac import require_permission
from app.dependencies import get_dashboard_controller


router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_permission(PROJECTS_READ_ALL))],
)


@router.get(
    "/summary",
    summary="Summary view payload (KPIs + pie + delayed track + top org/division)",
    description=(
        "Single payload that powers the Summary screen. Returns global "
        "project bucket counts (ontrack / delayed / completed; the "
        "'Active' KPI tile is FE-derived as `total - completed`), "
        "the top-N delayed projects with their item delay info, the "
        "top-N vendor cards by project count, and the top-N division "
        "cards. Admin-tier (projects:read_all)."
    ),
)
def get_dashboard_summary(
    delay_min_days: int = Query(5, ge=1, le=365, alias="delayMinDays"),
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.summary(delay_min_days=delay_min_days)


@router.get(
    "/projects",
    summary="Project cards listing with filters",
    description=(
        "Returns project cards (id, name, vendor list, division, "
        "lifecycle status, bucket, progress %, item counters) with "
        "optional filters: `bucket` (total / active / ontrack / delayed "
        "/ completed), free-text `q` over id / code / name / division "
        "/ vendor names, `vendorId`, `division` code. Paginated — "
        "default 200 rows."
    ),
)
def list_dashboard_projects_route(
    bucket: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None, alias="vendorId"),
    division: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500, alias="pageSize"),
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.projects(
        bucket=bucket,
        q=q,
        vendor_id=vendor_id,
        division=division,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/projects/{project_uuid}",
    summary="Project View payload (header + 5 KPIs + pie + delayed track)",
    description=(
        "Single payload for the Project View screen. Includes the "
        "project header card, 5 KPI tiles (Overall Progress, "
        "Milestones, Activities, Pending Approvals — static 0 in v1, "
        "Delayed), pie counts over M/A items, and delayed-track rows "
        "for items above `delayMinDays`."
    ),
)
def get_dashboard_project_detail(
    project_uuid: str,
    delay_min_days: int = Query(5, ge=1, le=365, alias="delayMinDays"),
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.project_detail(
        project_id=project_uuid, delay_min_days=delay_min_days,
    )


@router.get(
    "/projects/{project_uuid}/items",
    summary="M/A drill-down rows under a project (with filters)",
    description=(
        "Drill-down for KPI clicks. Returns milestone and / or activity "
        "rows under a project. Filters: `kind` (milestone | activity), "
        "`bucket` (ontrack | delayed | completed), `milestoneId` (only "
        "rows under one milestone), `minDelay` (days)."
    ),
)
def get_dashboard_project_items(
    project_uuid: str,
    kind: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
    milestone_id: Optional[str] = Query(None, alias="milestoneId"),
    min_delay: Optional[int] = Query(None, ge=0, alias="minDelay"),
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.project_items(
        project_id=project_uuid,
        kind=kind,
        bucket=bucket,
        milestone_id=milestone_id,
        min_delay=min_delay,
    )


@router.get(
    "/organisations",
    summary="Organization view grid + active/inactive vendor pie",
    description=(
        "Vendor cards for the Organization view top page. Each card "
        "carries the vendor's project count split by bucket. The pie "
        "block at the top shows vendor catalog distribution by "
        "`active` flag."
    ),
)
def list_dashboard_organisations(
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.organisations()


@router.get(
    "/organisations/{vendor_id}",
    summary="Vendor detail page (KPI counts + project pie + project list)",
    description=(
        "Drill-down when a vendor card is clicked. Returns the vendor's "
        "project list as cards, KPI counts (total / completed / ontrack "
        "/ delayed), and the corresponding pie counts."
    ),
)
def get_dashboard_organisation_detail(
    vendor_id: str,
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.organisation_detail(vendor_id=vendor_id)
