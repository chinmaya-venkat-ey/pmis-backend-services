"""Role-assignment endpoints (doc 41).

Owns three router surfaces:

  * /api/v3/users/{id}/role-assignments   — assignment CRUD per user
  * /api/v3/projects/{id}/role-assignments — assignment CRUD per project +
                                              the project drill-down view
                                              (per the FE mock)
  * /api/v3/vendors/{id}/projects          — Org-Mgmt landing view
"""
from .routes import (
    user_role_assignments_router,
    project_role_assignments_router,
    vendor_projects_router,
)

__all__ = [
    "user_role_assignments_router",
    "project_role_assignments_router",
    "vendor_projects_router",
]
