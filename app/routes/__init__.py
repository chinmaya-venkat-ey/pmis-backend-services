"""Router composer for pmis-user-management.

All business routers are mounted under the ``/user`` prefix. Health probes
(``/health``, ``/ready``) live at the app root so nginx / k8s can hit them
without auth.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes import (
    auth_routes,
    health_routes,
    permission_routes,
    role_assignment_routes,
    role_grants_routes,
    role_routes,
    user_routes,
)


user_router = APIRouter(prefix="/user")
user_router.include_router(auth_routes.router)
user_router.include_router(user_routes.router)
user_router.include_router(role_routes.router)
user_router.include_router(permission_routes.router)
user_router.include_router(role_assignment_routes.user_assignments_router)
user_router.include_router(role_assignment_routes.project_assignments_router)
user_router.include_router(role_assignment_routes.vendor_listing_router)
user_router.include_router(role_grants_routes.router)


__all__ = ["user_router", "health_routes"]
