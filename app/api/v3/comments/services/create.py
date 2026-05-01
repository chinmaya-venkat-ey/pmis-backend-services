"""Create-comment service.

Handles the body + optional files in one transaction:
  1. Verify target exists.
  2. Validate body and/or files were supplied (at least one).
  3. Persist the comment row.
  4. For each uploaded file: validate (size, extension), save bytes
     to storage, persist attachment row pointing at the comment.
  5. Hydrate attachments back onto the returned domain object.

If anything fails partway, the DB transaction rolls back AND any
already-written files are deleted. No orphans.
"""
from typing import List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from .....core.config import settings
from .....domain.comments.comment import Comment
from .....infrastructure.db.repositories.attachment_repository import (
    AttachmentRepository,
)
from .....infrastructure.db.repositories.comment_repository import (
    CommentRepository,
)
from .....infrastructure.storage import (
    StorageUnavailableError,
    get_storage,
)
from .....infrastructure.storage.file_storage import file_extension
from .....shared.service_result import ServiceResult

from .._target_helper import is_valid_target_kind, target_exists


_MAX_BODY_LEN = 5000


def _allowed_extensions() -> set[str]:
    raw = settings.ATTACHMENTS_ALLOWED_EXTENSIONS or ""
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def create_comment(
    db: Session,
    *,
    target_kind: str,
    target_id: str,
    body: str,
    files: Optional[List[UploadFile]],
    author_user_id: int,
) -> ServiceResult[Comment]:
    files = files or []

    # ---- Validation -----------------------------------------------------

    if not is_valid_target_kind(target_kind):
        return ServiceResult.fail(
            error=f"Invalid target_kind '{target_kind}'.",
            error_type="validation_error",
        )

    body = (body or "").strip()
    if not body and not files:
        return ServiceResult.fail(
            error="Comment must have either text or at least one attachment.",
            error_type="validation_error",
        )

    if len(body) > _MAX_BODY_LEN:
        return ServiceResult.fail(
            error=f"Comment body too long. Maximum {_MAX_BODY_LEN} characters.",
            error_type="validation_error",
        )

    if not target_exists(db, target_kind, target_id):
        return ServiceResult.fail(
            error=f"Target {target_kind} '{target_id}' not found.",
            error_type="not_found",
        )

    # Per-file validation (size + extension whitelist).
    allowed_exts = _allowed_extensions()
    max_bytes = settings.ATTACHMENTS_MAX_BYTES
    file_specs = []  # collected after validation
    for upload in files:
        # Read the actual size by seeking. UploadFile.size is sometimes
        # None depending on the spool path; stat the underlying file.
        upload.file.seek(0, 2)  # seek to end
        size = upload.file.tell()
        upload.file.seek(0)     # rewind for streaming write
        if size > max_bytes:
            return ServiceResult.fail(
                error=(
                    f"File '{upload.filename}' is {size} bytes; "
                    f"maximum is {max_bytes}."
                ),
                error_type="validation_error",
                details={"file": upload.filename, "size": size, "max": max_bytes},
            )
        ext = file_extension(upload.filename or "")
        if not ext or ext not in allowed_exts:
            return ServiceResult.fail(
                error=(
                    f"File '{upload.filename}' has disallowed extension "
                    f"'.{ext}'. Allowed: {', '.join(sorted(allowed_exts))}."
                ),
                error_type="validation_error",
                details={"file": upload.filename, "extension": ext},
            )
        file_specs.append({
            "upload": upload,
            "size": size,
            "extension": ext,
        })

    # ---- Persist comment + attachments ---------------------------------

    storage = get_storage()
    written_keys: List[str] = []  # for rollback on failure

    try:
        comment = CommentRepository(db).create(
            target_kind=target_kind,
            target_id=target_id,
            body=body,
            author_user_id=author_user_id,
        )

        attach_repo = AttachmentRepository(db)
        attachments = []
        for spec in file_specs:
            up = spec["upload"]
            key = storage.generate_storage_key(up.filename or "unnamed")
            storage.save(key, up.file)
            written_keys.append(key)
            attachment = attach_repo.create(
                comment_id=comment.id,
                target_kind=None,
                target_id=None,
                original_filename=up.filename or "unnamed",
                storage_key=key,
                mime_type=up.content_type or "application/octet-stream",
                size_bytes=spec["size"],
                uploaded_by_user_id=author_user_id,
            )
            attachments.append(attachment)

        comment.attachments = attachments
        db.commit()
        return ServiceResult.ok(comment)

    except StorageUnavailableError as e:
        db.rollback()
        # Best-effort cleanup of any files written before the failure.
        for k in written_keys:
            try:
                storage.delete(k)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"File storage unavailable: {e}",
            error_type="storage_unavailable",
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        for k in written_keys:
            try:
                storage.delete(k)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"Failed to create comment: {e}",
            error_type="internal_error",
        )
