"""Dashboard routes (admin / super_admin only).

All endpoints are gated by ``require_admin()`` — anonymous callers get
401, non-admin authenticated callers get 403. The dependency is
defined once at the router level so every route inherits it.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.errors import NotFoundError
from ....core.middleware.rbac import require_admin
from ....infrastructure.db.session import get_db

from .controller import DashboardController


router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[require_admin()],
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
        "cards. Admin-only."
    ),
)
def get_dashboard_summary(
    request: Request,
    delayMinDays: int = Query(5, ge=1, le=365),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.summary(db, delay_min_days=delayMinDays)


@router.get(
    "/projects",
    summary="Project cards listing with filters",
    description=(
        "Returns project cards (id, name, vendor list, division, "
        "lifecycle status, bucket, progress %, item counters) with "
        "optional filters: `bucket` (total / active / ontrack / "
        "delayed / completed), free-text `q` over id / code / name / "
        "division / vendor names, `vendorId`, `division` code. "
        "Paginated — default 200 rows."
    ),
)
def list_dashboard_projects_route(
    request: Request,
    bucket: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    vendorId: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.projects(
        db,
        bucket=bucket,
        q=q,
        vendor_id=vendorId,
        division=division,
        page=page,
        page_size=pageSize,
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
    request: Request,
    project_uuid: str,
    delayMinDays: int = Query(5, ge=1, le=365),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.project_detail(
        db, project_id=project_uuid, delay_min_days=delayMinDays,
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
    request: Request,
    project_uuid: str,
    kind: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
    milestoneId: Optional[str] = Query(None),
    minDelay: Optional[int] = Query(None, ge=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.project_items(
        db,
        project_id=project_uuid,
        kind=kind,
        bucket=bucket,
        milestone_id=milestoneId,
        min_delay=minDelay,
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
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.organisations(db)


@router.get(
    "/organisations/{vendor_id}",
    summary="Vendor detail page (KPI counts + project pie + project list)",
    description=(
        "Drill-down when a vendor card is clicked. Returns the vendor's "
        "project list as cards, KPI counts (total / completed / "
        "ontrack / delayed), and the corresponding pie counts."
    ),
)
def get_dashboard_organisation_detail(
    request: Request,
    vendor_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return DashboardController.organisation_detail(db, vendor_id=vendor_id)
