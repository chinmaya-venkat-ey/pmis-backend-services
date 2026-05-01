"""Comment routes.

Four targets (milestone/activity/task/subtask) × {POST, GET} = 8
endpoints + a single DELETE on a comment id. We register the same
controller method per target_kind to keep the dispatcher trivial.

POST endpoints accept multipart/form-data:
  - body: str   (Form field, optional but body or files required)
  - files: list (File field, zero or more)

GET endpoints accept:
  - offset (page number, 1-indexed)
  - pageSize (1..100)
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_authenticated, require_permission
from ....infrastructure.db.session import get_db
from .controller import CommentController
from .permissions import COMMENTS_CREATE, COMMENTS_READ, COMMENTS_DELETE


router = APIRouter(tags=["comments"])


# ---- Per-kind POST + GET (bulk-registered for brevity) -----------------

# Map URL path segment (plural) → internal target_kind (singular).
_KIND_BY_PATH = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}


def _make_create_endpoint(target_kind: str):
    """Factory — produces a route handler bound to a specific target_kind."""
    async def handler(
        request: Request,
        target_id: str,
        body: str = Form(""),
        files: Optional[List[UploadFile]] = File(None),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        return CommentController.create(
            request, target_kind, target_id, body, files, db,
        )
    handler.__name__ = f"create_{target_kind}_comment"
    return handler


def _make_list_endpoint(target_kind: str):
    def handler(
        request: Request,
        target_id: str,
        offset: int = Query(1, ge=1),
        pageSize: int = Query(20, ge=1, le=100),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        return CommentController.list(
            request, target_kind, target_id, offset, pageSize, db,
        )
    handler.__name__ = f"list_{target_kind}_comments"
    return handler


for _path, _kind in _KIND_BY_PATH.items():
    router.add_api_route(
        f"/{_path}/{{target_id}}/comments",
        _make_create_endpoint(_kind),
        methods=["POST"],
        dependencies=[require_permission(COMMENTS_CREATE)],
        summary=f"Create a comment on a {_kind}",
        description=(
            "Create a comment with optional file attachments via "
            "multipart/form-data. Either a non-empty body or at least one "
            "file is required."
        ),
        status_code=201,
    )
    router.add_api_route(
        f"/{_path}/{{target_id}}/comments",
        _make_list_endpoint(_kind),
        methods=["GET"],
        dependencies=[require_permission(COMMENTS_READ)],
        summary=f"List comments under a {_kind} (newest first)",
    )


# ---- Comment-id-scoped DELETE -----------------------------------------

@router.delete(
    "/comments/{comment_id}",
    dependencies=[require_authenticated()],
    summary="Soft-delete a comment (author or admin only)",
)
def delete_comment(
    request: Request,
    comment_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CommentController.delete(request, comment_id, db)
