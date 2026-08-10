"""CommentRepository — Doc-35 send-event polymorphic comments + attachments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple, Union

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.pagination import paginate
from app.models.comment import Comment


_TARGET_KINDS = {"project", "milestone", "activity", "task", "subtask"}


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
            paginate(stmt, offset, page_size)
        ).scalars().all()
        return list(rows), total

    def create(
        self, *,
        target_kind: str, target_id: str,
        author_user_id: str,
        body: Optional[str] = None,
        attachments: Optional[list] = None,
        category: Optional[str] = None,
    ) -> Comment:
        if target_kind not in _TARGET_KINDS:
            raise ValueError(f"target_kind {target_kind!r} not in {_TARGET_KINDS}")
        row = Comment(
            target_kind=target_kind,
            target_id=target_id,
            author_user_id=author_user_id,
            body=body,
            attachments=attachments,
            category=category,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_attachments_for_target(
        self, target_kind: str, target_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
        category: Optional[str] = None,
        exclude_category: Optional[Union[str, Sequence[str]]] = None,
    ) -> Tuple[List[Comment], int]:
        """List body-IS-NULL comment rows (attachment-only sends) for a
        target. Monolith parity: ordered OLDEST FIRST (``created_at
        ASC``) — distinct from the regular comment list which is
        newest-first.

        ``category`` restricts to rows with that exact classifier (e.g.
        ``'actual_start_reason'``); ``exclude_category`` drops rows with it —
        either a single classifier or a collection of them (e.g. the general
        attachment list hides all the date-change reason documents)."""
        clauses = [
            Comment.target_kind == target_kind,
            Comment.target_id == target_id,
            Comment.body.is_(None),
        ]
        if category is not None:
            clauses.append(Comment.category == category)
        if exclude_category is not None:
            excluded = (
                [exclude_category] if isinstance(exclude_category, str)
                else list(exclude_category)
            )
            clauses.append(
                Comment.category.notin_(excluded) | Comment.category.is_(None)
            )
        if not include_deleted:
            clauses.append(Comment.deleted_at.is_(None))
        stmt = select(Comment).where(and_(*clauses)).order_by(Comment.created_at.asc())
        total = self.db.execute(
            select(func.count()).select_from(Comment).where(and_(*clauses))
        ).scalar_one()
        rows = self.db.execute(
            paginate(stmt, offset, page_size)
        ).scalars().all()
        return list(rows), total

    def list_for_project_tree(
        self,
        project_id: str,
        *,
        milestone_ids: List[str],
        activity_ids: List[str],
        task_ids: List[str],
        subtask_ids: List[str],
        offset: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Comment], int]:
        """List every live comment row attached to the project itself OR any
        entity in its M/A/T/S subtree. Newest first; tie-break on id for
        stable pagination across same-second bursts."""
        from sqlalchemy import or_

        clauses = [
            and_(
                Comment.target_kind == "project",
                Comment.target_id == project_id,
            ),
        ]
        if milestone_ids:
            clauses.append(and_(
                Comment.target_kind == "milestone",
                Comment.target_id.in_(milestone_ids),
            ))
        if activity_ids:
            clauses.append(and_(
                Comment.target_kind == "activity",
                Comment.target_id.in_(activity_ids),
            ))
        if task_ids:
            clauses.append(and_(
                Comment.target_kind == "task",
                Comment.target_id.in_(task_ids),
            ))
        if subtask_ids:
            clauses.append(and_(
                Comment.target_kind == "subtask",
                Comment.target_id.in_(subtask_ids),
            ))

        where_expr = (
            and_(or_(*clauses), Comment.deleted_at.is_(None))
            if len(clauses) > 1 else
            and_(clauses[0], Comment.deleted_at.is_(None))
        )

        total = self.db.execute(
            select(func.count()).select_from(Comment).where(where_expr)
        ).scalar_one()
        rows = self.db.execute(
            paginate(
                select(Comment).where(where_expr)
                .order_by(Comment.created_at.desc(), Comment.id.desc()),
                offset, page_size,
            )
        ).scalars().all()
        return list(rows), total

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
