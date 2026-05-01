"""Upload a standalone attachment (no comment).

Distinct from the comment-attachment flow because it's a single-file
upload directly tied to a target node. Used when the user wants to
attach a file without writing a comment.
"""
from fastapi import UploadFile
from sqlalchemy.orm import Session

from .....core.config import settings
from .....domain.comments.attachment import Attachment
from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....infrastructure.storage import (
    StorageUnavailableError,
    get_storage,
)
from .....infrastructure.storage.file_storage import file_extension
from .....shared.service_result import ServiceResult

from ...comments._target_helper import is_valid_target_kind, target_exists


def _allowed_extensions() -> set[str]:
    raw = settings.ATTACHMENTS_ALLOWED_EXTENSIONS or ""
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def upload_standalone_attachment(
    db: Session,
    *,
    target_kind: str,
    target_id: str,
    upload: UploadFile,
    uploaded_by_user_id: int,
) -> ServiceResult[Attachment]:
    if not is_valid_target_kind(target_kind):
        return ServiceResult.fail(
            error=f"Invalid target_kind '{target_kind}'.",
            error_type="validation_error",
        )

    if upload is None or upload.filename is None:
        return ServiceResult.fail(
            error="No file uploaded.",
            error_type="validation_error",
        )

    if not target_exists(db, target_kind, target_id):
        return ServiceResult.fail(
            error=f"Target {target_kind} '{target_id}' not found.",
            error_type="not_found",
        )

    # Size + extension validation.
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)

    max_bytes = settings.ATTACHMENTS_MAX_BYTES
    if size > max_bytes:
        return ServiceResult.fail(
            error=(
                f"File '{upload.filename}' is {size} bytes; "
                f"maximum is {max_bytes}."
            ),
            error_type="validation_error",
            details={"file": upload.filename, "size": size, "max": max_bytes},
        )

    ext = file_extension(upload.filename)
    allowed = _allowed_extensions()
    if not ext or ext not in allowed:
        return ServiceResult.fail(
            error=(
                f"File '{upload.filename}' has disallowed extension "
                f"'.{ext}'. Allowed: {', '.join(sorted(allowed))}."
            ),
            error_type="validation_error",
            details={"file": upload.filename, "extension": ext},
        )

    # Persist.
    storage = get_storage()
    written_key = None
    try:
        key = storage.generate_storage_key(upload.filename)
        storage.save(key, upload.file)
        written_key = key

        attachment = AttachmentRepository(db).create(
            comment_id=None,
            target_kind=target_kind,
            target_id=target_id,
            original_filename=upload.filename,
            storage_key=key,
            mime_type=upload.content_type or "application/octet-stream",
            size_bytes=size,
            uploaded_by_user_id=uploaded_by_user_id,
        )
        db.commit()
        return ServiceResult.ok(attachment)

    except StorageUnavailableError as e:
        db.rollback()
        if written_key:
            try:
                storage.delete(written_key)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"File storage unavailable: {e}",
            error_type="storage_unavailable",
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        if written_key:
            try:
                storage.delete(written_key)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"Failed to upload attachment: {e}",
            error_type="internal_error",
        )
