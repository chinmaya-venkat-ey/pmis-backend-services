"""Repository for comments (doc 35: unified send-event model).

Returns domain ``Comment`` objects (not ORM models). Joins user info on
list/get reads so the API can embed author display details without an
N+1 lookup at the controller layer. Attachments live as a JSON list
on each row — no separate attachments table to query.

Soft-delete is the default — every read filters ``deleted_at IS NULL``
unless ``include_deleted=True`` is passed (admin/audit paths only).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ....domain.comments.comment import AttachmentInfo, Comment
from ..models.comment import CommentModel
from ..models.user import UserModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hydrate_attachments(raw: Any) -> List[AttachmentInfo]:
    """Convert the JSON column value into a typed list.

    Postgres JSONB returns a Python list/dict directly; SQLite JSON
    returns a string. Be tolerant of both, plus None / empty.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    return [AttachmentInfo.from_json_entry(e) for e in raw if isinstance(e, dict)]


def _to_domain(model: CommentModel, user: Optional[UserModel] = None) -> Comment:
    return Comment(
        id=model.id,
        target_kind=model.target_kind,
        target_id=model.target_id,
        body=model.body,
        author_user_id=model.author_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
        deleted_by=model.deleted_by,
        author_login=user.login if user else None,
        author_first_name=user.first_name if user else None,
        author_last_name=user.last_name if user else None,
        author_email=user.email if user else None,
        attachments=_hydrate_attachments(model.attachments),
    )


def _serialize_attachments(items: Optional[List[AttachmentInfo]]) -> Optional[list]:
    """Turn the typed list into the JSON column value the model stores.

    ``None`` and ``[]`` both persist as ``None`` (column NULL) so we
    don't end up with two equivalent on-the-wire representations of
    "no attachments".
    """
    if not items:
        return None
    return [a.to_dict() for a in items]


class CommentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----- Create -------------------------------------------------------

    def create(
        self,
        *,
        target_kind: str,
        target_id: str,
        body: Optional[str],
        attachments: Optional[List[AttachmentInfo]],
        author_user_id: str,
    ) -> Comment:
        """Insert a new send-event row.

        ``body`` may be None (file-only row), ``attachments`` may be
        empty (text-only row). Service layer enforces "at least one
        of the two".
        """
        model = CommentModel(
            target_kind=target_kind,
            target_id=target_id,
            body=body,
            attachments=_serialize_attachments(attachments),
            author_user_id=author_user_id,
        )
        self.db.add(model)
        self.db.flush()
        # Hydrate author info for the response without a second query.
        user = self.db.query(UserModel).filter(
            UserModel.id == author_user_id,
        ).first()
        return _to_domain(model, user)

    # ----- Read ---------------------------------------------------------

    def get_by_id(
        self, comment_id: str, *, include_deleted: bool = False,
    ) -> Optional[Comment]:
        q = (
            self.db.query(CommentModel, UserModel)
            .outerjoin(UserModel, UserModel.id == CommentModel.author_user_id)
            .filter(CommentModel.id == comment_id)
        )
        if not include_deleted:
            q = q.filter(CommentModel.deleted_at.is_(None))
        row = q.first()
        if not row:
            return None
        comment_model, user_model = row
        return _to_domain(comment_model, user_model)

    def list_by_target(
        self,
        target_kind: str,
        target_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        include_deleted: bool = False,
        attachment_only: Optional[bool] = None,
    ) -> Tuple[List[Comment], int]:
        """Return active comments for a target, newest first.

        ``attachment_only``: pass ``True`` to filter to file-only rows
        (body NULL); used by the GET /<entity>/{id}/attachments endpoint
        to keep its old behaviour intact post-doc-34. Pass ``None`` (the
        default) to return every send-event regardless of body presence.

        Returns (items, total). Total is the unfiltered active count —
        used by the API for pagination metadata.
        """
        q = (
            self.db.query(CommentModel, UserModel)
            .outerjoin(UserModel, UserModel.id == CommentModel.author_user_id)
            .filter(
                and_(
                    CommentModel.target_kind == target_kind,
                    CommentModel.target_id == target_id,
                )
            )
        )
        if not include_deleted:
            q = q.filter(CommentModel.deleted_at.is_(None))
        if attachment_only is True:
            # File-only rows: body is NULL or whitespace-only. We can't
            # easily filter "whitespace-only" in SQL portably; treat
            # NULL bodies as the canonical attachment-only marker
            # (matches what the create service writes).
            q = q.filter(CommentModel.body.is_(None))
        elif attachment_only is False:
            q = q.filter(CommentModel.body.isnot(None))

        total = q.count()
        rows = (
            q.order_by(desc(CommentModel.created_at), desc(CommentModel.id))
            .offset(offset)
            .limit(limit)
            .all()
        )
        comments = [_to_domain(c, u) for (c, u) in rows]
        return comments, total

    # ----- Soft delete --------------------------------------------------

    def soft_delete(
        self, comment_id: str, actor_id: int,
    ) -> Optional[Comment]:
        """Idempotent soft-delete. Returns the (now-deleted) comment, or
        None if no row exists."""
        model = self.db.query(CommentModel).filter(
            CommentModel.id == comment_id,
        ).first()
        if not model:
            return None
        if model.deleted_at is None:
            model.deleted_at = _utcnow()
            model.deleted_by = actor_id
            self.db.flush()
        user = self.db.query(UserModel).filter(
            UserModel.id == model.author_user_id,
        ).first()
        return _to_domain(model, user)
