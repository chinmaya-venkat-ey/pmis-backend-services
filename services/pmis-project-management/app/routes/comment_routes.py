"""Routes for /project/{kind}/{id}/comments/* and /project/comments/{id}/delete.

target_kind is derived from URL prefix: milestone / activity / task / subtask.
Project_id is resolved from the target row in the service layer.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.controllers.comment_controller import CommentController
from app.core.errors import (
    ActivityNotFoundError,
    MilestoneNotFoundError,
    SubtaskNotFoundError,
    TaskNotFoundError,
)
from app.core.permissions import COMMENTS_CREATE, COMMENTS_MODERATE, COMMENTS_READ
from app.core.rbac import require_permission
from app.db import get_db
from app.dependencies import get_comment_controller, get_current_user_id
from app.repositories.activity_repository import ActivityRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.subtask_repository import SubtaskRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.comment import (
    CommentCreateRequest,
    CommentModerateRequest,
    CommentResponse,
)


def _resolve_project_id(db, target_kind: str, target_id: str) -> str:
    """Look up the project_id of the comment's target (raises if not found)."""
    if target_kind == "milestone":
        row = MilestoneRepository(db).get_by_id(target_id)
        if row is None:
            raise MilestoneNotFoundError(f"Milestone {target_id!r} not found")
        return row.project_id
    if target_kind == "activity":
        row = ActivityRepository(db).get_by_id(target_id)
        if row is None:
            raise ActivityNotFoundError(f"Activity {target_id!r} not found")
        return row.project_id
    if target_kind == "task":
        row = TaskRepository(db).get_by_id(target_id)
        if row is None:
            raise TaskNotFoundError(f"Task {target_id!r} not found")
        return row.project_id
    if target_kind == "subtask":
        row = SubtaskRepository(db).get_by_id(target_id)
        if row is None:
            raise SubtaskNotFoundError(f"Subtask {target_id!r} not found")
        return row.project_id
    raise ValueError(f"unknown target_kind {target_kind!r}")


# --- per-target routers: list + create -----------------------------------

def _make_target_router(target_kind: str, plural: str) -> APIRouter:
    """Build the /project/{plural}/{id}/comments/* router for a given target_kind."""
    r = APIRouter(prefix=f"/{plural}", tags=["comments"])

    @r.get(
        "/{target_id}/comments/list",
        summary=f"List comments on a {target_kind}",
        dependencies=[Depends(require_permission(COMMENTS_READ))],
    )
    def _list(
        target_id: str,
        offset: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        include_deleted: bool = Query(False),
        controller: CommentController = Depends(get_comment_controller),
    ):
        return controller.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    @r.post(
        "/{target_id}/comments/create",
        response_model=CommentResponse,
        status_code=status.HTTP_201_CREATED,
        summary=f"Post a comment on a {target_kind} (body or attachments required)",
        dependencies=[Depends(require_permission(COMMENTS_CREATE))],
        responses={409: {"description": "Attachment too large or extension disallowed"}},
    )
    def _create(
        target_id: str,
        payload: CommentCreateRequest,
        controller: CommentController = Depends(get_comment_controller),
        caller_user_id: str = Depends(get_current_user_id),
        db=Depends(get_db),
    ):
        project_id = _resolve_project_id(db, target_kind, target_id)
        return controller.create(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            payload=payload,
            caller_user_id=caller_user_id,
        )

    return r


milestones_comments_router = _make_target_router("milestone", "milestones")
activities_comments_router = _make_target_router("activity", "activities")
tasks_comments_router = _make_target_router("task", "tasks")
subtasks_comments_router = _make_target_router("subtask", "subtasks")


# --- /project/comments/{id}/delete --------------------------------------

comment_router = APIRouter(prefix="/comments", tags=["comments"])


@comment_router.delete(
    "/{comment_id}/delete",
    response_model=CommentResponse,
    summary="Moderate a comment (admin/super_admin) - TOMBSTONE semantics",
    description=(
        "Round-7 Q8: this does NOT remove the row. body and attachments are "
        "blanked; deleted_at, deleted_by, and moderation_reason capture the "
        "audit trail. author_user_id is preserved so the tombstone still names "
        "the original author. A moderation_reason is required in the request body."
    ),
    dependencies=[Depends(require_permission(COMMENTS_MODERATE))],
)
def moderate_comment(
    comment_id: str,
    payload: CommentModerateRequest,
    controller: CommentController = Depends(get_comment_controller),
    caller_user_id: str = Depends(get_current_user_id),
    db=Depends(get_db),
):
    # Resolve project_id from the comment's target so the audit log
    # attribution is correct.
    row = controller.service.get_by_id(comment_id)
    project_id = _resolve_project_id(db, row.target_kind, row.target_id)
    return controller.moderate_delete(
        comment_id,
        moderation_reason=payload.moderation_reason,
        caller_user_id=caller_user_id,
        project_id=project_id,
    )
