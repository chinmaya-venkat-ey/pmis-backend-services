"""Router composer for pmis-project-management.

Business routers are mounted under the ``/project`` prefix. Health probes
(``/health``, ``/ready``) live at the app root.

The dev-only attachment download fallback (``GET /files/{key}``) lives at
the app root too — exposed here as ``attachment_routes.files_router`` and
mounted by ``app.main`` outside the ``/project`` prefix.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.routes import (
    activity_routes,
    attachment_routes,
    comment_routes,
    dashboard_routes,
    health_routes,
    milestone_routes,
    project_routes,
    subtask_routes,
    task_routes,
    tree_routes,
)


project_router = APIRouter(prefix="/project")
project_router.include_router(project_routes.router)
project_router.include_router(milestone_routes.project_scoped_router)
project_router.include_router(milestone_routes.router)
project_router.include_router(activity_routes.milestone_scoped_router)
project_router.include_router(activity_routes.router)
project_router.include_router(task_routes.activity_scoped_router)
project_router.include_router(task_routes.router)
project_router.include_router(subtask_routes.task_scoped_router)
project_router.include_router(subtask_routes.router)
project_router.include_router(comment_routes.milestones_comments_router)
project_router.include_router(comment_routes.activities_comments_router)
project_router.include_router(comment_routes.tasks_comments_router)
project_router.include_router(comment_routes.subtasks_comments_router)
project_router.include_router(comment_routes.comment_router)
project_router.include_router(attachment_routes.router)
project_router.include_router(dashboard_routes.router)
project_router.include_router(tree_routes.router)


__all__ = ["project_router", "health_routes", "attachment_routes"]
