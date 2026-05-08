"""Attachment routes (doc 35: collapsed onto the comments table).

What changed:
  - Endpoint paths are unchanged on the wire, so FE keeps working:
      POST   /<entity>/{id}/attachments    upload one file as a body-empty comment
      GET    /<entity>/{id}/attachments    list body-empty comments
      DELETE /attachments/{id}              soft-delete that comment row
  - The streaming download endpoint
      GET /attachments/{id}/download
    is REMOVED. The URL of the file is stored directly on the comment
    row (``attachments[i].url``) and the FE fetches bytes from there.
    For dev / legacy URLs the BE mounts a fallback ``GET /files/{key}``
    route in ``app.main`` that streams bytes from local storage.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_authenticated, require_permission
from ....infrastructure.db.session import get_db
from .controller import AttachmentController
from ..comments.permissions import (
    ATTACHMENTS_CREATE,
    COMMENTS_READ,
)


router = APIRouter(tags=["attachments"])


_KIND_BY_PATH = {
    "milestones": "milestone",
    "activities": "activity",
    "tasks": "task",
    "subtasks": "subtask",
}


def _make_upload_endpoint(target_kind: str):
    async def handler(
        request: Request,
        target_id: str,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        return AttachmentController.upload(
            request, target_kind, target_id, file, db,
        )
    handler.__name__ = f"upload_{target_kind}_attachment"
    return handler


def _make_list_endpoint(target_kind: str):
    def handler(
        request: Request,
        target_id: str,
        offset: int = Query(1, ge=1),
        pageSize: int = Query(20, ge=1, le=100),
        db: Session = Depends(get_db),
    ) -> Dict[str, Any]:
        return AttachmentController.list(
            request, target_kind, target_id, offset, pageSize, db,
        )
    handler.__name__ = f"list_{target_kind}_attachments"
    return handler


for _path, _kind in _KIND_BY_PATH.items():
    router.add_api_route(
        f"/{_path}/{{target_id}}/attachments",
        _make_upload_endpoint(_kind),
        methods=["POST"],
        dependencies=[require_permission(ATTACHMENTS_CREATE)],
        summary=f"Upload a standalone attachment to a {_kind}",
        description=(
            "Upload a single file via multipart/form-data (field name "
            "``file``). Doc 35: stored as a comment row with NULL body "
            "and one attachment entry on the JSON column. The response "
            "carries the file's public URL, fetched directly by the FE."
        ),
        status_code=201,
    )
    router.add_api_route(
        f"/{_path}/{{target_id}}/attachments",
        _make_list_endpoint(_kind),
        methods=["GET"],
        dependencies=[require_permission(COMMENTS_READ)],
        summary=f"List standalone attachments under a {_kind}",
        description=(
            "Doc 35: returns comments rows whose body is NULL "
            "(attachment-only sends), newest-first."
        ),
    )


# ---- id-scoped routes -------------------------------------------------

@router.delete(
    "/attachments/{attachment_id}",
    dependencies=[require_authenticated()],
    summary="Soft-delete an attachment (uploader or admin only)",
    description=(
        "Doc 35: aliased to DELETE /comments/{id}. The id resolves to "
        "a comment row whose body is NULL. Bytes on disk are kept "
        "until the retention cron sweeps them."
    ),
)
def delete_attachment(
    request: Request,
    attachment_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return AttachmentController.delete(request, attachment_id, db)
