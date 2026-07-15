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

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Query

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
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    delay_min_days: Annotated[int, Query(ge=1, le=365, alias="delayMinDays")] = 5,
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
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    bucket: Annotated[Optional[str], Query()] = None,
    q: Annotated[Optional[str], Query()] = None,
    vendor_id: Annotated[Optional[str], Query(alias="vendorId")] = None,
    division: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[Optional[int], Query(ge=1, alias="pageSize")] = None,
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
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    delay_min_days: Annotated[int, Query(ge=1, le=365, alias="delayMinDays")] = 5,
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
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    kind: Annotated[Optional[str], Query()] = None,
    bucket: Annotated[Optional[str], Query()] = None,
    milestone_id: Annotated[Optional[str], Query(alias="milestoneId")] = None,
    min_delay: Annotated[Optional[int], Query(ge=0, alias="minDelay")] = None,
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


# =========================================================================
# Aggregated "view" endpoints (new FE dashboard). Additive — the six
# endpoints above are unchanged. Payload shapes match the frontend spec;
# sla/tickets/meetings degrade to available:false until wired.
# =========================================================================


@router.get(
    "/summary-view",
    summary="Summary dashboard view (KPIs, finance, approvals, trends, top org/division)",
    description=(
        "Single aggregated payload for the Summary dashboard: KPI tiles, "
        "project-status split, payment-by-phase, cost composition, "
        "payment-by-organisation, approval-workflow stages, monthly trend, "
        "top organisations/divisions and the delayed-project track. "
        "`sla`, `tickets`, `meetings` carry `available` flags. "
        "Admin-tier (projects:read_all)."
    ),
)
def get_dashboard_summary_view(
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    delay_min_days: Annotated[int, Query(ge=1, le=365, alias="delayMinDays")] = 1,
    top_n: Annotated[int, Query(ge=1, le=50, alias="topN")] = 5,
    authorization: Annotated[Optional[str], Header()] = None,
) -> Dict[str, Any]:
    return controller.summary_view(
        delay_min_days=delay_min_days, top_n=top_n, bearer=authorization,
    )


@router.get(
    "/projects/{project_uuid}/full",
    summary="Full project dashboard view (header + KPIs + finance + approvals + items)",
    description=(
        "Single aggregated payload for one project's dashboard: header, "
        "KPI tiles, status counts, finance (contract/scheduled/cost split "
        "+ by-phase), approval workflow, delayed track and the flat "
        "milestone/activity item list. `sla` degrades to available:false."
    ),
)
def get_dashboard_project_full(
    project_uuid: str,
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
) -> Dict[str, Any]:
    return controller.project_full(project_id=project_uuid)


@router.get(
    "/organisation-view",
    summary="Organisation dashboard view — all organisations (mode=all)",
    description=(
        "Aggregated payload across all organisations: KPI tiles, project "
        "status split, leaderboard, payment-by-organisation and the full "
        "organisation grid (per-org project buckets + contract/scheduled "
        "value). `slaByOrganization` is empty until SLA is wired."
    ),
)
def get_dashboard_organisation_view(
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    top_n: Annotated[int, Query(ge=1, le=50, alias="topN")] = 8,
) -> Dict[str, Any]:
    return controller.organisation_view(top_n=top_n)


@router.get(
    "/organisations/{organisation_id}/view",
    summary="Organisation dashboard view — single organisation (mode=single)",
    description=(
        "Aggregated payload for one organisation: KPI tiles, project "
        "status split & overview, payment-by-project, contract-vs-"
        "scheduled, top delayed projects, tickets/meetings blocks and the "
        "organisation's project cards."
    ),
)
def get_dashboard_organisation_single(
    organisation_id: str,
    controller: Annotated[DashboardController, Depends(get_dashboard_controller)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Dict[str, Any]:
    return controller.organisation_single(
        organisation_id=organisation_id, bearer=authorization,
    )


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
