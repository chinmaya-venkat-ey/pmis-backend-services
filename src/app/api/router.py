"""Central v3 router for pmis-project-service.

In-use modules only. Per the backport plan, the dormant monolith
modules — meetings, work_packages, work_package_types, project_members,
users, roles, permissions — are NOT registered here. user-service owns
the auth surface; the rest are dead in the current product flow.
"""
from fastapi import APIRouter

from .v3.activities import (
    activities_milestone_router,
    activities_router,
)
from .v3.attachments import router as attachments_router
from .v3.catalogs import catalogs_router
from .v3.comments import router as comments_router
from .v3.master_data import master_data_router
from .v3.milestones import (
    milestones_project_router,
    milestones_router,
)
from .v3.projects import router as projects_router
from .v3.resource_types import router as resource_types_router
from .v3.subtasks import (
    subtasks_task_router,
    subtasks_router,
)
from .v3.tasks import (
    tasks_activity_router,
    tasks_router,
)
from .v3.tree import router as tree_router
from .v3.vendors import router as vendors_router

api_v3_router = APIRouter(prefix="/api/v3")

# Project lifecycle
api_v3_router.include_router(projects_router)

# M/A/T/S hierarchy
api_v3_router.include_router(milestones_project_router)
api_v3_router.include_router(milestones_router)
api_v3_router.include_router(activities_milestone_router)
api_v3_router.include_router(activities_router)
api_v3_router.include_router(tasks_activity_router)
api_v3_router.include_router(tasks_router)
api_v3_router.include_router(subtasks_task_router)
api_v3_router.include_router(subtasks_router)
api_v3_router.include_router(tree_router)

# Catalog modules (legacy)
api_v3_router.include_router(vendors_router)
api_v3_router.include_router(resource_types_router)
api_v3_router.include_router(catalogs_router)

# Consolidated master-data CRUD (doc 20). Lives under /api/v3/master/*.
# Supersedes the legacy per-catalog endpoints above; those remain
# functional during the FE migration window with a Deprecation header.
api_v3_router.include_router(master_data_router)

# Comments + attachments (polymorphic across M/A/T/S targets)
api_v3_router.include_router(comments_router)
api_v3_router.include_router(attachments_router)
