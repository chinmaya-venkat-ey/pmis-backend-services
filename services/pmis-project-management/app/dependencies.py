"""FastAPI dependency factories for pmis-project-management."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.controllers.activity_controller import ActivityController
from app.controllers.comment_controller import CommentController
from app.controllers.dashboard_controller import DashboardController
from app.controllers.milestone_controller import MilestoneController
from app.controllers.project_controller import ProjectController
from app.controllers.subtask_controller import SubtaskController
from app.controllers.task_controller import TaskController
from app.controllers.tree_controller import TreeController
from app.core.errors import UnauthorizedError
from app.db import get_db


def get_current_user_id(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise UnauthorizedError("Authentication required", code="AUTH_REQUIRED")
    return uid


def get_optional_current_user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


def get_caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def get_caller_role_name(request: Request) -> Optional[str]:
    """Round-7 deprecated. The FSM gates by permission code, not role name.
    Kept as a no-op for backwards compatibility; new code should NOT use this.
    """
    return getattr(request.state, "caller_role_name", None)


# Controllers ---------------------------------------------------------------

def get_project_controller(db: Session = Depends(get_db)) -> ProjectController:
    return ProjectController(db)


def get_milestone_controller(db: Session = Depends(get_db)) -> MilestoneController:
    return MilestoneController(db)


def get_activity_controller(db: Session = Depends(get_db)) -> ActivityController:
    return ActivityController(db)


def get_task_controller(db: Session = Depends(get_db)) -> TaskController:
    return TaskController(db)


def get_subtask_controller(db: Session = Depends(get_db)) -> SubtaskController:
    return SubtaskController(db)


def get_comment_controller(db: Session = Depends(get_db)) -> CommentController:
    return CommentController(db)


def get_dashboard_controller(db: Session = Depends(get_db)) -> DashboardController:
    return DashboardController(db)


def get_tree_controller(db: Session = Depends(get_db)) -> TreeController:
    return TreeController(db)
