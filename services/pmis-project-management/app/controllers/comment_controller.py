"""CommentController."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.comment import CommentCreateRequest, CommentResponse
from app.services.comment_service import CommentService


class CommentController:
    def __init__(self, db: Session):
        self.db = db
        self.service = CommentService(db)

    def list_for_target(self, target_kind: str, target_id: str, *, offset=1, page_size=50, include_deleted=False):
        rows, total = self.service.list_for_target(
            target_kind, target_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )
        return {
            "items": [CommentResponse.model_validate(r) for r in rows],
            "total": total, "offset": offset, "page_size": page_size,
        }

    def create(
        self,
        *,
        project_id: str,
        target_kind: str,
        target_id: str,
        payload: CommentCreateRequest,
        caller_user_id: str,
    ) -> CommentResponse:
        row = self.service.create(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            payload=payload,
            caller_user_id=caller_user_id,
        )
        return CommentResponse.model_validate(row)

    def moderate_delete(
        self, comment_id: str, *,
        moderation_reason: str,
        caller_user_id: str,
        project_id: Optional[str] = None,
    ) -> CommentResponse:
        """Round-7 Q8 tombstone delete (admin/super_admin only)."""
        row = self.service.moderate_delete(
            comment_id,
            moderation_reason=moderation_reason,
            caller_user_id=caller_user_id,
            project_id=project_id,
        )
        return CommentResponse.model_validate(row)
