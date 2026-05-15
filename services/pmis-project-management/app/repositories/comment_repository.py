"""CommentRepository — Doc-35 send-event polymorphic comments + attachments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.comment import Comment


_TARGET_KINDS = {"milestone", "activity", "task", "subtask"}


class CommentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, comment_id: str) -> Optional[Comment]:
        return self.db.get(Comment, comment_id)

    def list_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ) -> Tuple[List[Comment], int]:
        clauses = [
            Comment.target_kind == target_kind,
            Comment.target_id == target_id,
        ]
        if not include_deleted:
            clauses.append(Comment.deleted_at.is_(None))
        stmt = select(Comment).where(and_(*clauses)).order_by(Comment.created_at.desc())
        total = self.db.execute(
            select(func.count()).select_from(Comment).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            stmt.offset(max(0, offset - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def create(
        self, *,
        target_kind: str, target_id: str,
        author_user_id: str,
        body: Optional[str] = None,
        attachments: Optional[list] = None,
    ) -> Comment:
        if target_kind not in _TARGET_KINDS:
            raise ValueError(f"target_kind {target_kind!r} not in {_TARGET_KINDS}")
        row = Comment(
            target_kind=target_kind,
            target_id=target_id,
            author_user_id=author_user_id,
            body=body,
            attachments=attachments,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def soft_delete(self, row: Comment, *, deleted_by: Optional[str]) -> Comment:
        row.deleted_at = datetime.now(timezone.utc)
        row.deleted_by = deleted_by
        self.db.flush()
        return row

    def restore(self, row: Comment) -> Comment:
        row.deleted_at = None
        row.deleted_by = None
        self.db.flush()
        return row
