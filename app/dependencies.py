"""FastAPI dependency factories for pmis-project-management."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.controllers.activity_controller import ActivityController
from app.controllers.approval_inbox_controller import ApprovalInboxController
from app.controllers.attachment_controller import AttachmentController
from app.controllers.comment_controller import CommentController
from app.controllers.critical_path_controller import CriticalPathController
from app.controllers.dashboard_controller import DashboardController
from app.controllers.finance_controller import FinanceController
from app.controllers.milestone_controller import MilestoneController
from app.controllers.project_controller import ProjectController
from app.controllers.subtask_controller import SubtaskController
from app.controllers.task_controller import TaskController
from app.controllers.team_controller import TeamController
from app.controllers.tree_controller import TreeController
from app.core.rbac import AUTH_REQUIRED_MESSAGE
from app.core.errors import UnauthorizedError
from app.db import get_db


# ---------------------------------------------------------------- request state

def get_current_user_id(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise UnauthorizedError(AUTH_REQUIRED_MESSAGE, code="auth_required")
    return uid


def get_optional_current_user_id(request: Request) -> Optional[str]:
    return getattr(request.state, "user_id", None)


def get_caller_is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


# ---------------------------------------------------------------- controllers

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


def get_attachment_controller(db: Session = Depends(get_db)) -> AttachmentController:
    return AttachmentController(db)


def get_dashboard_controller(db: Session = Depends(get_db)) -> DashboardController:
    return DashboardController(db)


def get_tree_controller(db: Session = Depends(get_db)) -> TreeController:
    return TreeController(db)


def get_critical_path_controller(db: Session = Depends(get_db)) -> CriticalPathController:
    return CriticalPathController(db)


def get_team_controller(db: Session = Depends(get_db)) -> TeamController:
    return TeamController(db)


def get_approval_inbox_controller(
    db: Session = Depends(get_db),
) -> ApprovalInboxController:
    return ApprovalInboxController(db)


def get_finance_controller(db: Session = Depends(get_db)) -> FinanceController:
    return FinanceController(db)
