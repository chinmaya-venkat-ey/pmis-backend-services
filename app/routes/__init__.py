"""Router composer for pmis-project-management.

Business routers mount under ``/project``. Health probes (``/health``,
``/ready``) and the dev attachment fallback (``GET /files/{key}``) live
at the app root — mounted by ``app.main`` outside the ``/project`` prefix.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes import (
    activity_routes,
    approval_inbox_routes,
    attachment_routes,
    catalog_routes,
    comment_routes,
    critical_path_routes,
    dashboard_cron_routes,
    dashboard_routes,
    finance_routes,
    health_routes,
    milestone_routes,
    payment_routes,
    project_routes,
    qgr_routes,
    subtask_routes,
    task_routes,
    team_routes,
    tree_routes,
    vendor_routes,
)


project_router = APIRouter(prefix="/api/v3")

# Projects + their project-scoped sub-routes (role-assignments,
# assignable-users, audit-logs, discussion-feed, attachments).
project_router.include_router(project_routes.router)

# M/A/T/S hierarchy — project-scoped create/list AND id-scoped CRUD.
project_router.include_router(milestone_routes.project_scoped_router)
project_router.include_router(milestone_routes.router)
project_router.include_router(activity_routes.milestone_scoped_router)
project_router.include_router(activity_routes.router)
project_router.include_router(task_routes.activity_scoped_router)
project_router.include_router(task_routes.router)
project_router.include_router(subtask_routes.task_scoped_router)
project_router.include_router(subtask_routes.router)

# Polymorphic comments + per-target attachments + comment-id / attachment-id
# operations. Both modules register their per-target routes inside one
# router each.
project_router.include_router(comment_routes.router)
project_router.include_router(attachment_routes.router)

# Read-only surfaces.
project_router.include_router(dashboard_routes.router)
# Dashboard snapshot cron (shared-secret gated, NOT user-auth gated).
project_router.include_router(dashboard_cron_routes.router)
project_router.include_router(tree_routes.router)
project_router.include_router(critical_path_routes.router)

# Catalog lookups (/api/v3/divisions, /api/v3/priorities, etc.) and vendor
# management (/api/v3/vendors/*) — matching VM project service (port 8003).
project_router.include_router(catalog_routes.router)
project_router.include_router(vendor_routes.router)

# Team management — Manage-Team page endpoints.
project_router.include_router(team_routes.project_team_router)
project_router.include_router(team_routes.activity_team_router)
project_router.include_router(team_routes.associated_users_router)

# Activity Approval Inbox — list + detail for the workflow review UI.
project_router.include_router(approval_inbox_routes.router)

# Project finance — GET/PATCH /api/v3/projects/{uuid}/finance.
project_router.include_router(finance_routes.router)

# Payment module — Project-Finance screen (cost items, payment terms, QRG,
# CCN cap, aggregated page). Project-scoped create/list + id-scoped CRUD.
project_router.include_router(payment_routes.cost_item_project_scoped_router)
project_router.include_router(payment_routes.cost_item_router)
project_router.include_router(payment_routes.payment_term_project_scoped_router)
project_router.include_router(payment_routes.payment_term_router)
project_router.include_router(payment_routes.payment_page_router)
project_router.include_router(payment_routes.cycle_count_router)

# QGR (Quarterly Guaranteed Revenue) — RFP §5.23.2. CRUD used by
# contract-management's NpqpService (via cross-schema SELECT — no HTTP
# hop) and by the FE settlement setup page.
project_router.include_router(qgr_routes.router)


__all__ = ["project_router", "health_routes", "attachment_routes"]
