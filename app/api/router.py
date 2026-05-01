"""Central v3 router for pmis-project-service.

This service owns the project-management endpoints under /api/v3/*.
Module routers are wired in here as they get ported in subsequent
phases (vendors, catalogs, projects, milestones, activities, tasks,
    subtasks, comments, attachments, tree).
"""
from fastapi import APIRouter

from .v3.activities import (
    activities_milestone_router,
    activities_router,
    )
from .v3.attachments import router as attachments_router
from .v3.catalogs import router as catalogs_router
from .v3.comments import router as comments_router
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
api_v3_router.include_router(resource_types_router)
api_v3_router.include_router(catalogs_router)
api_v3_router.include_router(vendors_router)
api_v3_router.include_router(projects_router)
api_v3_router.include_router(milestones_project_router)
api_v3_router.include_router(milestones_router)
api_v3_router.include_router(activities_milestone_router)
api_v3_router.include_router(activities_router)
api_v3_router.include_router(tasks_activity_router)
api_v3_router.include_router(tasks_router)
api_v3_router.include_router(subtasks_task_router)
api_v3_router.include_router(subtasks_router)
api_v3_router.include_router(tree_router)
api_v3_router.include_router(comments_router)
api_v3_router.include_router(attachments_router)

# All planned phases (1-12) wired. M/A/T/S backbone + comments +
# attachments + tree + lifecycle complete.
