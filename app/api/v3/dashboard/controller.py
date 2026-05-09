"""Dashboard controller — orchestrates request → service → envelope.

All endpoints are gated by ``require_admin`` at the route layer (admin
or super_admin). The controller stays free of permission checks itself
to avoid double-gating.
"""
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from .services import (
    get_organisation_detail,
    get_project_detail,
    get_project_items,
    get_summary,
    list_dashboard_projects,
    list_organisations,
)


class DashboardController:
    """Controller for dashboard read endpoints."""

    @staticmethod
    def summary(
        db: Session,
        *,
        delay_min_days: int,
    ) -> JSONResponse:
        data = get_summary(db, delay_min_days=delay_min_days)
        return BaseController.ok(data=data)

    @staticmethod
    def projects(
        db: Session,
        *,
        bucket: Optional[str],
        q: Optional[str],
        vendor_id: Optional[str],
        division: Optional[str],
        page: int,
        page_size: int,
    ) -> JSONResponse:
        data = list_dashboard_projects(
            db,
            bucket=bucket,
            q=q,
            vendor_id=vendor_id,
            division=division,
            page=page,
            page_size=page_size,
        )
        return BaseController.ok(data=data)

    @staticmethod
    def project_detail(
        db: Session,
        *,
        project_id: str,
        delay_min_days: int,
    ) -> JSONResponse:
        data = get_project_detail(
            db, project_id=project_id, delay_min_days=delay_min_days,
        )
        return BaseController.ok(data=data)

    @staticmethod
    def project_items(
        db: Session,
        *,
        project_id: str,
        kind: Optional[str],
        bucket: Optional[str],
        milestone_id: Optional[str],
        min_delay: Optional[int],
    ) -> JSONResponse:
        data = get_project_items(
            db,
            project_id=project_id,
            kind=kind,
            bucket=bucket,
            milestone_id=milestone_id,
            min_delay=min_delay,
        )
        return BaseController.ok(data=data)

    @staticmethod
    def organisations(db: Session) -> JSONResponse:
        data = list_organisations(db)
        return BaseController.ok(data=data)

    @staticmethod
    def organisation_detail(
        db: Session,
        *,
        vendor_id: str,
    ) -> JSONResponse:
        data = get_organisation_detail(db, vendor_id=vendor_id)
        return BaseController.ok(data=data)
