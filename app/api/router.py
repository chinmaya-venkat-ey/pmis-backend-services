"""Central v3 router — owns /api/v3/users/*, /api/v3/master/* (user-mgmt
slim slice), and the doc-41 scoped role-assignment + project-mapping
surface. The legacy /api/v3/roles/* and /api/v3/permissions/* are still
mounted (back-compat) but include-ordered LAST so Swagger UI surfaces
the canonical paths first.

Tag order in /docs follows include order, so the visual hierarchy is:
  users → master_data (canonical catalog) → role-assignments (doc 41)
  → ... → roles (DEPRECATED) → permissions (DEPRECATED).

``/api/v3/master/notification_templates`` is owned by
PMIS-notification-service (doc 38). Other master-data slices
(divisions, vendors, project_categories, etc.) stay on the monolith.
"""
from fastapi import APIRouter

from .v3.master_data import router as master_data_router
from .v3.permissions import permissions_router
from .v3.role_assignments import (
    project_role_assignments_router,
    user_role_assignments_router,
    vendor_projects_router,
)
from .v3.roles import router as roles_router
from .v3.users import router as users_router


api_v3_router = APIRouter(prefix="/api/v3")

# ---- Active surface (canonical) ---------------------------------------
api_v3_router.include_router(users_router)
api_v3_router.include_router(master_data_router)

# Doc 41 — scoped role assignments + project-mapping views. Mounted
# directly below master_data so Swagger lists the new surface next to
# the catalog it works against.
api_v3_router.include_router(user_role_assignments_router)
api_v3_router.include_router(project_role_assignments_router)
api_v3_router.include_router(vendor_projects_router)

# ---- DEPRECATED routers (kept for back-compat; superseded by /api/v3/master/*)
# Both stamp ``Deprecation: true`` + ``Link: rel="successor-version"``
# on every response. Mounted last so Swagger UI puts them at the
# bottom of the tag list.
api_v3_router.include_router(roles_router)
api_v3_router.include_router(permissions_router)
