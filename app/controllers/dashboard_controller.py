"""DashboardController — thin facade in front of ``DashboardService``.

Six endpoints, one per public method. The controller doesn't do any
permission checks itself — the route layer gates every method with
``require_permission(PROJECTS_READ_ALL)`` (admin-tier in practice).

Monolith parity: every dashboard payload is returned as a RAW dict
under ``data`` (no ``_type`` stamp). The ``_bare: True`` marker
(stripped by the wrap layer) tells ``HalApiRoute`` to skip its
``hal_resource`` envelope, otherwise FastAPI's
``Dict[str, Any]`` return annotation would cause the wrap layer to
derive ``_type: "Dict"`` which monolith does not emit.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.dashboard_service import DashboardService
from app.services.dashboard_view_service import DashboardViewService


def _bare(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Tag a dashboard payload so the HAL wrap layer passes it through
    unchanged (just camelizes keys; no ``_type`` / ``_links`` envelope).
    """
    payload["_bare"] = True
    return payload


class DashboardController:
    def __init__(self, db: Session):
        self.db = db
        self.service = DashboardService(db)
        # The four new aggregated "view" payloads (summary-view, project
        # /full, organisation-view, single org /view). Ticket / meeting
        # providers are injected in a later phase; None => degrade to
        # available:false so the endpoints work without the Java services.
        self.view_service = DashboardViewService(db)

    # ---- new aggregated view endpoints ---------------------------------

    def summary_view(self, *, delay_min_days: int, top_n: int) -> Dict[str, Any]:
        return _bare(self.view_service.get_summary_view(
            delay_min_days=delay_min_days, top_n=top_n,
        ))

    def project_full(self, *, project_id: str) -> Dict[str, Any]:
        return _bare(self.view_service.get_project_full(project_id=project_id))

    def organisation_view(self, *, top_n: int) -> Dict[str, Any]:
        return _bare(self.view_service.get_organisation_view(top_n=top_n))

    def organisation_single(self, *, organisation_id: str) -> Dict[str, Any]:
        return _bare(self.view_service.get_organisation_single(
            organisation_id=organisation_id,
        ))

    # ---- original endpoints --------------------------------------------

    def summary(self, *, delay_min_days: int) -> Dict[str, Any]:
        return _bare(self.service.get_summary(delay_min_days=delay_min_days))

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
        return _bare(self.service.list_projects(
            bucket=bucket,
            q=q,
            vendor_id=vendor_id,
            division=division,
            page=page,
            page_size=page_size,
        ))

    def project_detail(
        self, *, project_id: str, delay_min_days: int,
    ) -> Dict[str, Any]:
        return _bare(self.service.get_project_detail(
            project_id=project_id, delay_min_days=delay_min_days,
        ))

    def project_items(
        self,
        *,
        project_id: str,
        kind: Optional[str],
        bucket: Optional[str],
        milestone_id: Optional[str],
        min_delay: Optional[int],
    ) -> Dict[str, Any]:
        return _bare(self.service.get_project_items(
            project_id=project_id,
            kind=kind,
            bucket=bucket,
            milestone_id=milestone_id,
            min_delay=min_delay,
        ))

    def organisations(self) -> Dict[str, Any]:
        return _bare(self.service.list_organisations())

    def organisation_detail(self, *, vendor_id: str) -> Dict[str, Any]:
        return _bare(self.service.get_organisation_detail(vendor_id=vendor_id))
