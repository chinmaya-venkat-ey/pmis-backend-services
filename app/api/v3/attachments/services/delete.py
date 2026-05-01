"""Soft-delete an attachment.

Author OR admin only. Bytes remain on disk; the retention cron will
purge them after ATTACHMENTS_RETENTION_DAYS.
"""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....shared.service_result import ServiceResult


def delete_attachment(
    db: Session,
    *,
    attachment_id: str,
    actor_id: int,
    actor_is_admin: bool,
) -> ServiceResult[bool]:
    repo = AttachmentRepository(db)
    attachment = repo.get_by_id(attachment_id)
    if attachment is None:
        return ServiceResult.fail(
            error=f"Attachment {attachment_id} not found.",
            error_type="not_found",
        )

    if attachment.uploaded_by_user_id != actor_id and not actor_is_admin:
        return ServiceResult.fail(
            error="Only the uploader or an admin can delete this attachment.",
            error_type="authorization_error",
        )

    try:
        repo.soft_delete(attachment_id, actor_id)
        db.commit()
        return ServiceResult.ok(True)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to delete attachment: {e}",
            error_type="internal_error",
        )
