"""CommentService — Doc-35 send-event polymorphic comments + attachments.

Targets: ``project`` / ``milestone`` / ``activity`` / ``task`` / ``subtask``.

Enforces the "body OR attachments" invariant + per-attachment size +
extension checks (configured via ``settings.attachments_*``).

Deletion contract (matches monolith): author or admin can soft-delete
a comment. ``deleted_at`` + ``deleted_by`` are set; ``body`` and
``attachments`` are PRESERVED (soft-delete is reversible). No moderation
reason is required.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import (
    AttachmentDisallowedExtensionError,
    AttachmentTooLargeError,
    CommentBodyOrAttachmentRequiredError,
    CommentNotFoundError,
    ForbiddenError,
)
from app.repositories.comment_repository import CommentRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.schemas.comment import CommentCreateRequest


class CommentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ---------------------------------------------------------------- read

    def get_by_id(self, comment_id: str):
        """Returns the LIVE comment row for write-paths (delete + audit).
        Monolith parity: soft-deleted rows are invisible to a fresh
        DELETE — the caller gets a 404 (``"Comment <uuid> not found."``)
        rather than a 200-with-already-deleted-payload."""
        row = self.repo.get_by_id(comment_id)
        if row is None or row.deleted_at is not None:
            raise CommentNotFoundError(f"Comment {comment_id} not found.")
        return row

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ):
        return self.repo.list_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def list_attachments_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ):
        """Body-IS-NULL comment rows under a target (Doc-35 attachment-only sends)."""
        return self.repo.list_attachments_for_target(
            target_kind, target_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    # ---------------------------------------------------------------- write

    def create(
        self,
        *,
        project_id: str,
        target_kind: str,
        target_id: str,
        body: Optional[str],
        attachments: Optional[List[dict]],
        caller_user_id: str,
    ):
        """Insert one comment row. ``attachments`` is the JSONB list ready
        to persist (each entry already a ``{url, filename, mimeType,
        sizeBytes, uploadedAt}`` dict — built by the route layer from
        either the JSON request body or the multipart files via the file
        client)."""
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        if not body_clean and not atts:
            # Monolith parity: this surfaces with the generic
            # ``validation_error`` identifier — NOT a specific
            # ``comment_body_or_attachment_required`` code.
            from app.core.errors import ValidationError
            raise ValidationError(
                "Comment must have either text or at least one attachment.",
            )
        # Defensive body-length guard (Pydantic enforces the same 5000
        # cap on the wire; this catches direct service callers).
        if body_clean is not None and len(body_clean) > 5000:
            from app.core.errors import ValidationError
            raise ValidationError(
                "Comment body too long. Maximum 5000 characters."
            )
        self._validate_attachments(atts)
        row = self.repo.create(
            target_kind=target_kind,
            target_id=target_id,
            author_user_id=caller_user_id,
            body=body_clean,
            attachments=atts or None,
        )
        self.audit.write(
            project_id=project_id,
            target_kind="comment", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={
                "target_kind": target_kind,
                "target_id": target_id,
                "n_attachments": len(atts),
            },
        )
        self.db.commit()
        return row

    def delete(
        self, comment_id: str,
        *,
        caller_user_id: str,
        caller_is_admin: bool,
        caller_permissions: Optional[set] = None,
        project_id: Optional[str] = None,
    ):
        """Author-or-moderator soft-delete. Sets ``deleted_at`` +
        ``deleted_by``; body and attachments are preserved (soft-delete is
        reversible).

        §3.1 (2026-06-02 audit) item 3: replaced the ``caller_is_admin``
        short-circuit with an explicit ``comments:moderate`` check. Admins
        hold this code via r005, so the behavior is unchanged for them;
        non-admin moderators (if any role is later granted the code) are
        now also authorized.
        """
        from app.core.permissions import COMMENTS_MODERATE

        row = self.get_by_id(comment_id)
        held = caller_permissions or set()
        if (
            row.author_user_id != caller_user_id
            and COMMENTS_MODERATE not in held
        ):
            raise ForbiddenError(
                "Only the author or a caller with comments:moderate can "
                "delete a comment.",
                code="comment_delete_forbidden",
            )
        self.repo.soft_delete(row, deleted_by=caller_user_id)
        if project_id is not None:
            self.audit.write(
                project_id=project_id,
                target_kind="comment", target_id=row.id,
                action="delete", actor_user_id=caller_user_id,
            )
        self.db.commit()
        return row

    # ---------------------------------------------------- attachment guards

    def _validate_attachments(self, atts: List[dict]) -> None:
        max_bytes = settings.attachments_max_bytes
        allowed = {
            ext.strip().lower()
            for ext in settings.attachments_allowed_extensions.split(",")
            if ext.strip()
        }
        for a in atts:
            size = a.get("sizeBytes") or a.get("size_bytes")
            name = a.get("filename") or ""
            if size is not None and size > max_bytes:
                raise AttachmentTooLargeError(
                    f"Attachment {name!r} exceeds max size ({max_bytes} bytes)",
                    details={"filename": name, "max_bytes": max_bytes},
                )
            if allowed and "." in name:
                ext = name.rsplit(".", 1)[1].lower()
                if ext not in allowed:
                    raise AttachmentDisallowedExtensionError(
                        f"Attachment extension {ext!r} not allowed",
                        details={"filename": name, "allowed": sorted(allowed)},
                    )
