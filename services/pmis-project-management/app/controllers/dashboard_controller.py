"""DashboardController — thin facade in front of ``DashboardService``.

Six endpoints, one per public method. The controller doesn't do any
permission checks itself — the route layer gates every method with
``require_permission(PROJECTS_READ_ALL)`` (admin-tier in practice).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.dashboard_service import DashboardService


class DashboardController:
    def __init__(self, db: Session):
        self.db = db
        self.service = DashboardService(db)

    def summary(self, *, delay_min_days: int) -> Dict[str, Any]:
        return self.service.get_summary(delay_min_days=delay_min_days)

    def projects(
        self,
        *,
        bucket: Optional[str],
        q: Optional[str],
        vendor_id: Optional[str],
        division: Optional[str],
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        return self.service.list_projects(
            bucket=bucket,
            q=q,
            vendor_id=vendor_id,
            division=division,
            page=page,
            page_size=page_size,
        )

    def project_detail(
        self, *, project_id: str, delay_min_days: int,
    ) -> Dict[str, Any]:
        return self.service.get_project_detail(
            project_id=project_id, delay_min_days=delay_min_days,
        )

    def project_items(
        self,
        *,
        project_id: str,
        kind: Optional[str],
        bucket: Optional[str],
        milestone_id: Optional[str],
        min_delay: Optional[int],
    ) -> Dict[str, Any]:
        return self.service.get_project_items(
            project_id=project_id,
            kind=kind,
            bucket=bucket,
            milestone_id=milestone_id,
            min_delay=min_delay,
        )

    def organisations(self) -> Dict[str, Any]:
        return self.service.list_organisations()

    def organisation_detail(self, *, vendor_id: str) -> Dict[str, Any]:
        return self.service.get_organisation_detail(vendor_id=vendor_id)
