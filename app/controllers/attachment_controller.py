"""AttachmentController — per-target attachment endpoints (multipart upload,
list, delete).

Targets: ``project`` / ``milestone`` / ``activity`` / ``task`` / ``subtask``.
Storage rides on the shared comments table (Doc-35) — uploads create a
``body IS NULL`` comment row with the file metadata in the JSONB column.

Per-kind response-shape split (monolith parity):
  * ``project``  POST -> bare Collection dict; GET -> flat file rows.
  * ``M/A/T/S``  POST -> Comment HAL envelope; GET -> Collection of
    Comment HAL elements + ``pageSize`` / ``offset``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.controllers.comment_controller import CommentController
from app.schemas.comment import CommentDeleteSuccess, CommentResponse
from app.services.attachment_service import AttachmentService


class AttachmentController:
    def __init__(self, db: Session):
        self.db = db
        self.service = AttachmentService(db)
        self._comments = CommentController(db)

    def upload(
        self,
        target_kind: str,
        target_id: str,
        files: List[UploadFile],
        *, caller_user_id: str,
    ) -> Union[Dict[str, Any], CommentResponse]:
        if target_kind == "project":
            return self.service.upload(
                target_kind, target_id, files,
                caller_user_id=caller_user_id,
            )
        row = self.service.upload_row(
            target_kind, target_id, files,
            caller_user_id=caller_user_id,
        )
        return self._comments._to_response(row)

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Dict[str, Any]:
        return self.service.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def delete(
        self, attachment_id: str, *,
        caller_user_id: str, caller_is_admin: bool,
        caller_permissions: Optional[set] = None,
    ) -> CommentDeleteSuccess:
        """DELETE /project/attachments/{id} is aliased to comment delete —
        the id refers to the body-NULL comment row.

        Monolith parity: the underlying comment-delete plumbing
        (permission + audit + soft-delete) is reused via
        ``CommentController.delete`` but the SUCCESS wording is
        attachment-specific (``"Attachment <uuid> deleted."`` instead of
        ``"Comment <uuid> deleted."``). NotFound messages still say
        ``"Comment <uuid> not found."`` — that monolith inconsistency
        falls out for free because both layers raise via the same
        ``CommentNotFoundError``.

        §3.1 (2026-06-02 audit): ``caller_permissions`` must be threaded
        through because DELETE /comments/{id} is now gated on
        author-or-``comments:moderate`` instead of author-or-admin.
        """
        self._comments.delete(
            attachment_id,
            caller_user_id=caller_user_id,
            caller_is_admin=caller_is_admin,
            caller_permissions=caller_permissions,
        )
        return CommentDeleteSuccess(
            message=f"Attachment {attachment_id} deleted.",
        )
