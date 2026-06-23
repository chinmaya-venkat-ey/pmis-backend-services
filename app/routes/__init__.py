"""Masters-svc API router composition.

Exposes a single `api_router` mounted at `/masters` in main.py. Each catalog
contributes its own sub-router. health_routes mount at the app root
(outside the prefix) per Decision 8d.

Catalog routes (per PLAN.md §2.4 verb-suffix scheme; Option C granular RBAC):
  /masters/divisions/*
  /masters/vendors/*  (+ /masters/vendors/{vendor_id}/projects/list)
  /masters/resource-types/*
  /masters/priorities/*
  /masters/project-categories/*
  /masters/activity-types/*
  /masters/activity-statuses/*
  /masters/milestone-statuses/*
  /masters/project-status-transitions/*
  /masters/notification-templates/*
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes.activity_status_routes import router as activity_status_router
from app.routes.activity_type_routes import router as activity_type_router
from app.routes.cost_type_routes import router as cost_type_router
from app.routes.division_routes import router as division_router
from app.routes.frequency_routes import router as frequency_router
from app.routes.milestone_status_routes import router as milestone_status_router
from app.routes.notification_template_routes import (
    router as notification_template_router,
)
from app.routes.payment_type_routes import router as payment_type_router
from app.routes.priority_routes import router as priority_router
from app.routes.project_category_routes import router as project_category_router
from app.routes.project_status_transition_routes import (
    router as project_status_transition_router,
)
from app.routes.resource_type_routes import router as resource_type_router
from app.routes.vendor_routes import router as vendor_router


api_router = APIRouter(prefix="/api/v3/master")
api_router.include_router(division_router)
api_router.include_router(vendor_router)
api_router.include_router(resource_type_router)
api_router.include_router(priority_router)
api_router.include_router(cost_type_router)
api_router.include_router(frequency_router)
api_router.include_router(payment_type_router)
api_router.include_router(project_category_router)
api_router.include_router(activity_type_router)
api_router.include_router(activity_status_router)
api_router.include_router(milestone_status_router)
api_router.include_router(project_status_transition_router)
api_router.include_router(notification_template_router)
