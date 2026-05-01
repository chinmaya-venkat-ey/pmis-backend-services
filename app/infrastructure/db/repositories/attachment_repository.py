"""Repository for attachment metadata.

Mirrors the comment repository pattern: returns domain objects, hydrates
uploader info, soft-delete by default, ordered newest-first on lists.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ....domain.comments.attachment import Attachment
from ..models.attachment import AttachmentModel
from ..models.user import UserModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_domain(
    model: AttachmentModel, user: Optional[UserModel] = None,
) -> Attachment:
    return Attachment(
        id=model.id,
        comment_id=model.comment_id,
        target_kind=model.target_kind,
        target_id=model.target_id,
        original_filename=model.original_filename,
        storage_key=model.storage_key,
        mime_type=model.mime_type,
        size_bytes=model.size_bytes,
        uploaded_by_user_id=model.uploaded_by_user_id,
        uploaded_at=model.uploaded_at,
        deleted_at=model.deleted_at,
        deleted_by=model.deleted_by,
        uploader_login=user.login if user else None,
        uploader_first_name=user.first_name if user else None,
        uploader_last_name=user.last_name if user else None,
    )


class AttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----- Create -------------------------------------------------------

    def create(
        self,
        *,
        comment_id: Optional[str],
        target_kind: Optional[str],
        target_id: Optional[str],
        original_filename: str,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        uploaded_by_user_id: int,
    ) -> Attachment:
        # Invariant: either comment_id is set, or both target_kind+target_id are set.
        if comment_id is None and (target_kind is None or target_id is None):
            raise ValueError(
                "Standalone attachment requires both target_kind and target_id."
            )
        model = AttachmentModel(
            comment_id=comment_id,
            target_kind=target_kind,
            target_id=target_id,
            original_filename=original_filename,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            uploaded_by_user_id=uploaded_by_user_id,
        )
        self.db.add(model)
        self.db.flush()
        user = self.db.query(UserModel).filter(
            UserModel.id == uploaded_by_user_id,
        ).first()
        return _to_domain(model, user)

    # ----- Read ---------------------------------------------------------

    def get_by_id(
        self, attachment_id: str, *, include_deleted: bool = False,
    ) -> Optional[Attachment]:
        q = (
            self.db.query(AttachmentModel, UserModel)
            .outerjoin(UserModel, UserModel.id == AttachmentModel.uploaded_by_user_id)
            .filter(AttachmentModel.id == attachment_id)
        )
        if not include_deleted:
            q = q.filter(AttachmentModel.deleted_at.is_(None))
        row = q.first()
        if not row:
            return None
        att_model, user_model = row
        return _to_domain(att_model, user_model)

    def list_by_comment(self, comment_id: str) -> List[Attachment]:
        rows = (
            self.db.query(AttachmentModel, UserModel)
            .outerjoin(UserModel, UserModel.id == AttachmentModel.uploaded_by_user_id)
            .filter(
                and_(
                    AttachmentModel.comment_id == comment_id,
                    AttachmentModel.deleted_at.is_(None),
                )
            )
            .order_by(desc(AttachmentModel.uploaded_at))
            .all()
        )
        return [_to_domain(a, u) for (a, u) in rows]

    def list_standalone_by_target(
        self,
        target_kind: str,
        target_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Attachment], int]:
        """Standalone attachments only (comment_id IS NULL). Newest first."""
        q = (
            self.db.query(AttachmentModel, UserModel)
            .outerjoin(UserModel, UserModel.id == AttachmentModel.uploaded_by_user_id)
            .filter(
                and_(
                    AttachmentModel.comment_id.is_(None),
                    AttachmentModel.target_kind == target_kind,
                    AttachmentModel.target_id == target_id,
                    AttachmentModel.deleted_at.is_(None),
                )
            )
        )
        total = q.count()
        rows = (
            q.order_by(desc(AttachmentModel.uploaded_at), desc(AttachmentModel.id))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_to_domain(a, u) for (a, u) in rows], total

    # ----- Soft delete --------------------------------------------------

    def soft_delete(
        self, attachment_id: str, actor_id: int,
    ) -> Optional[Attachment]:
        model = self.db.query(AttachmentModel).filter(
            AttachmentModel.id == attachment_id,
        ).first()
        if not model:
            return None
        if model.deleted_at is None:
            model.deleted_at = _utcnow()
            model.deleted_by = actor_id
            self.db.flush()
        user = self.db.query(UserModel).filter(
            UserModel.id == model.uploaded_by_user_id,
        ).first()
        return _to_domain(model, user)
