"""Router composer for pmis-user-management.

All business routers are mounted under the /api/v3 prefix to match the
reference API (VM port 8001). Health probes live at the app root.

The user service is the single source of authentication for the platform:
every other service validates JWTs by calling /api/v3/users/introspect.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes import (
    auth_routes,
    authz_routes,
    health_routes,
    permission_routes,
    role_assignment_routes,
    role_grants_routes,
    role_routes,
    user_routes,
)


user_router = APIRouter(prefix="/api/v3")
user_router.include_router(auth_routes.router)
user_router.include_router(authz_routes.router)
user_router.include_router(user_routes.router)
user_router.include_router(role_routes.router)
user_router.include_router(permission_routes.router)
user_router.include_router(role_assignment_routes.user_assignments_router)
user_router.include_router(role_assignment_routes.project_assignments_router)
user_router.include_router(role_assignment_routes.vendor_listing_router)
user_router.include_router(role_grants_routes.router)

# /api/v3/master/roles and /api/v3/master/permissions — canonical aliases
_master_router = APIRouter(prefix="/master")
_master_router.include_router(role_routes.router)
_master_router.include_router(permission_routes.router)
user_router.include_router(_master_router)


__all__ = ["user_router", "health_routes"]
