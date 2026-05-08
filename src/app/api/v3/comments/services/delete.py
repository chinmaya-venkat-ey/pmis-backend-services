"""Soft-delete a comment (doc 35: unified send-event model).

Author OR admin only. The whole row goes — body + attachments JSON
together. Bytes on disk are not deleted here; the retention cron
(future work) sweeps storage_keys whose comment rows are soft-deleted
older than ATTACHMENTS_RETENTION_DAYS.

Pre-doc-34 there was a soft-cascade that flipped the corresponding
attachment rows' deleted_at as well. That's gone — the rows are
collapsed, so soft-deleting the comment is equivalent.
"""
from sqlalchemy.orm import Session

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
        db.commit()
        return ServiceResult.ok(True)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to delete comment: {e}",
            error_type="internal_error",
        )
