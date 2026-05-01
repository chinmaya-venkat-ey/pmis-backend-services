"""Soft-delete a comment.

Authorization: the author OR an admin can delete. Anyone else gets 403.
Attachments belonging to this comment are also soft-deleted (the bytes
remain on disk until the retention cron purges them).
"""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....infrastructure.db.repositories.comment_repository import (
    CommentRepository,
)
from .....shared.service_result import ServiceResult


def delete_comment(
    db: Session,
    *,
    comment_id: str,
    actor_id: int,
    actor_is_admin: bool,
) -> ServiceResult[bool]:
    repo = CommentRepository(db)
    comment = repo.get_by_id(comment_id)
    if comment is None:
        return ServiceResult.fail(
            error=f"Comment {comment_id} not found.",
            error_type="not_found",
        )

    if comment.author_user_id != actor_id and not actor_is_admin:
        return ServiceResult.fail(
            error="Only the comment's author or an admin can delete it.",
            error_type="authorization_error",
        )

    try:
        repo.soft_delete(comment_id, actor_id)
        # Soft-cascade: mark attached files deleted too.
        att_repo = AttachmentRepository(db)
        for att in att_repo.list_by_comment(comment_id):
            att_repo.soft_delete(att.id, actor_id)
        db.commit()
        return ServiceResult.ok(True)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to delete comment: {e}",
            error_type="internal_error",
        )
