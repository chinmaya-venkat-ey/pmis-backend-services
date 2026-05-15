"""CommentService — Doc-35 send-event polymorphic comments + attachments.

Enforces the "body OR attachments" invariant + attachment-size + extension
checks (configured via settings.attachments_*). The actual file upload is
handled by route layer (multipart); this service just persists the
{url, filename, mimeType, sizeBytes, uploadedAt} envelope returned by the
file-server side.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import (
    AttachmentDisallowedExtensionError,
    AttachmentTooLargeError,
    CommentBodyOrAttachmentRequiredError,
    CommentNotFoundError,
)
from app.repositories.comment_repository import CommentRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.schemas.comment import CommentCreateRequest


class CommentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, comment_id: str):
        row = self.repo.get_by_id(comment_id)
        if row is None:
            raise CommentNotFoundError(f"Comment {comment_id!r} not found")
        return row

    def list_for_target(self, target_kind: str, target_id: str, *, offset=1, page_size=50, include_deleted=False):
        return self.repo.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def create(
        self,
        *,
        project_id: str,
        target_kind: str,
        target_id: str,
        payload: CommentCreateRequest,
        caller_user_id: str,
    ):
        body_present = bool(payload.body and payload.body.strip())
        atts = payload.attachments or []
        if not body_present and not atts:
            raise CommentBodyOrAttachmentRequiredError(
                "body or attachments must be present (Doc-35 send-event)",
            )
        self._validate_attachments(atts)
        row = self.repo.create(
            target_kind=target_kind,
            target_id=target_id,
            author_user_id=caller_user_id,
            body=payload.body,
            attachments=[a.model_dump(by_alias=True) for a in atts] if atts else None,
        )
        self.audit.write(
            project_id=project_id,
            target_kind="comment", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"target_kind": target_kind, "target_id": target_id, "n_attachments": len(atts)},
        )
        self.db.commit()
        return row

    def moderate_delete(
        self, comment_id: str, *,
        moderation_reason: str,
        caller_user_id: str,
        project_id: Optional[str] = None,
    ):
        """Round-7 Q8 TOMBSTONE delete (admin/super_admin only).

        The row is NOT removed. Mutations:
          - body         -> NULL
          - attachments  -> NULL
          - deleted_at   -> now (utc)
          - deleted_by   -> caller_user_id
          - moderation_reason -> caller-supplied reason

        author_user_id is preserved so the tombstone still names the original
        author. List endpoints with include_deleted=True return the tombstone
        with body/attachments null + the full audit trail.
        """
        from datetime import datetime, timezone

        row = self.get_by_id(comment_id)
        row.body = None
        row.attachments = None
        row.deleted_at = datetime.now(timezone.utc)
        row.deleted_by = caller_user_id
        row.moderation_reason = moderation_reason
        self.db.flush()

        if project_id is not None:
            self.audit.write(
                project_id=project_id,
                target_kind="comment", target_id=row.id,
                action="moderate", actor_user_id=caller_user_id,
                note=moderation_reason,
            )
        self.db.commit()
        return row

    # ------------------------------------------------------------------ attachment guards

    def _validate_attachments(self, atts) -> None:
        max_bytes = settings.attachments_max_bytes
        allowed = {
            ext.strip().lower()
            for ext in settings.attachments_allowed_extensions.split(",")
            if ext.strip()
        }
        for a in atts:
            if a.size_bytes is not None and a.size_bytes > max_bytes:
                raise AttachmentTooLargeError(
                    f"Attachment {a.filename!r} exceeds max size ({max_bytes} bytes)",
                    details={"filename": a.filename, "max_bytes": max_bytes},
                )
            if allowed and "." in a.filename:
                ext = a.filename.rsplit(".", 1)[1].lower()
                if ext not in allowed:
                    raise AttachmentDisallowedExtensionError(
                        f"Attachment extension {ext!r} not allowed",
                        details={"filename": a.filename, "allowed": sorted(allowed)},
                    )
