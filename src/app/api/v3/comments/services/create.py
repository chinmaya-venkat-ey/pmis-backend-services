"""Create-comment service (doc 35: unified send-event model).

A single insert into ``comments`` carries body + JSON attachments
together. Steps:

  1. Verify target exists.
  2. Validate body and/or files were supplied (at least one).
  3. Per-file validation (size, extension) BEFORE any upload.
  4. Upload each file via ``get_file_client()`` — writes bytes locally
     (or forwards to an external server when configured), returns the
     public URL + storage key + metadata.
  5. Persist a single ``comments`` row with the body and a JSON list
     of attachment-info objects.
  6. If anything fails after a file's bytes are already on disk,
     best-effort delete the bytes so we don't leak.

The previous two-table flow (one comments INSERT + N attachments
INSERTs) has been collapsed into one row + one JSON column.
"""
from typing import List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from .....core.config import settings
from .....domain.comments.comment import AttachmentInfo, Comment
from .....infrastructure.db.repositories.comment_repository import (
    CommentRepository,
)
from .....infrastructure.storage import (
    StorageUnavailableError,
    get_file_client,
)
from .....infrastructure.storage.file_storage import file_extension
from .....shared.file_content_check import validate_content_matches_extension
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
    body: Optional[str],
    files: Optional[List[UploadFile]],
    author_user_id: str,
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

    # Per-file validation (size + extension whitelist). Run BEFORE the
    # comment row is touched so an obviously-bad file doesn't leave an
    # orphan row.
    allowed_exts = _allowed_extensions()
    max_bytes = settings.ATTACHMENTS_MAX_BYTES
    for upload in files:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
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

        # Magic-byte / declared-extension content check. Catches renamed
        # payloads (evil.exe -> report.pdf) that pass the extension
        # whitelist but lie about their content. Project-service-only
        # post-demo client requirement; not present in monolith.
        sniff_buf = upload.file.read(262)
        upload.file.seek(0)
        is_valid, content_err = validate_content_matches_extension(sniff_buf, ext)
        if not is_valid:
            return ServiceResult.fail(
                error=content_err,
                error_type="validation_error",
                details={"file": upload.filename, "extension": ext},
            )

    # ---- Upload bytes + collect URLs -----------------------------------

    client = get_file_client()
    stored_keys: List[str] = []  # for rollback on later failure
    attachment_infos: List[AttachmentInfo] = []

    try:
        for upload in files:
            stored = client.upload(
                upload.file,
                upload.filename or "unnamed",
                upload.content_type or "application/octet-stream",
            )
            stored_keys.append(stored.storage_key)
            attachment_infos.append(AttachmentInfo(
                url=stored.url,
                filename=stored.filename,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                uploaded_at=stored.uploaded_at,
            ))

        # ---- Persist single comment row --------------------------------
        comment = CommentRepository(db).create(
            target_kind=target_kind,
            target_id=target_id,
            body=body or None,
            attachments=attachment_infos or None,
            author_user_id=author_user_id,
        )
        db.commit()
        return ServiceResult.ok(comment)

    except StorageUnavailableError as e:
        db.rollback()
        for k in stored_keys:
            try:
                client.delete(k)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"File storage unavailable: {e}",
            error_type="storage_unavailable",
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        for k in stored_keys:
            try:
                client.delete(k)
            except Exception:
                pass
        return ServiceResult.fail(
            error=f"Failed to create comment: {e}",
            error_type="internal_error",
        )
