"""Attachment routes.

Standalone uploads (no comment) per target kind, plus id-scoped
download + delete. Download is a streaming response, not an envelope.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_authenticated, require_permission
from ....infrastructure.db.session import get_db
from .controller import AttachmentController
from ..comments.permissions import (
    ATTACHMENTS_CREATE,
    ATTACHMENTS_DOWNLOAD,
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
            "`file`). The attachment is attached directly to the target "
            "node, not to a comment."
        ),
        status_code=201,
    )
    router.add_api_route(
        f"/{_path}/{{target_id}}/attachments",
        _make_list_endpoint(_kind),
        methods=["GET"],
        dependencies=[require_permission(COMMENTS_READ)],
        summary=f"List standalone attachments under a {_kind}",
    )


# ---- id-scoped routes -------------------------------------------------

@router.get(
    "/attachments/{attachment_id}/download",
    dependencies=[require_permission(ATTACHMENTS_DOWNLOAD)],
    summary="Download an attachment's file bytes",
    description=(
        "Streams the file bytes back. Sets Content-Disposition so the "
        "browser saves with the original filename."
    ),
)
def download_attachment(
    request: Request,
    attachment_id: str,
    db: Session = Depends(get_db),
):
    return AttachmentController.download(request, attachment_id, db)


@router.delete(
    "/attachments/{attachment_id}",
    dependencies=[require_authenticated()],
    summary="Soft-delete an attachment (uploader or admin only)",
)
def delete_attachment(
    request: Request,
    attachment_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return AttachmentController.delete(request, attachment_id, db)
