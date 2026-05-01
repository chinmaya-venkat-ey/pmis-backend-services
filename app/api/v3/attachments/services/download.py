"""Open the file bytes for an attachment so the controller can stream them.

Returns a ServiceResult carrying both the metadata (for the
Content-Disposition / Content-Type headers) and an opened file-like
object. Caller is responsible for closing the file (FastAPI's
StreamingResponse handles this when the stream is exhausted).
"""
from typing import Any, BinaryIO, Dict

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....infrastructure.storage import (
    StorageUnavailableError,
    get_storage,
)
from .....shared.service_result import ServiceResult


def open_attachment_for_download(
    db: Session,
    *,
    attachment_id: str,
) -> ServiceResult[Dict[str, Any]]:
    """Returns {"attachment": Attachment, "stream": BinaryIO}."""
    attachment = AttachmentRepository(db).get_by_id(attachment_id)
    if attachment is None:
        return ServiceResult.fail(
            error=f"Attachment {attachment_id} not found.",
            error_type="not_found",
        )

    storage = get_storage()
    try:
        stream: BinaryIO = storage.open(attachment.storage_key)
    except StorageUnavailableError as e:
        return ServiceResult.fail(
            error=f"File storage unavailable: {e}",
            error_type="storage_unavailable",
        )

    return ServiceResult.ok({
        "attachment": attachment,
        "stream": stream,
    })
