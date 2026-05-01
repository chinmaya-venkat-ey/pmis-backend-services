"""Upload a standalone attachment (no comment).

Distinct from the comment-attachment flow because it's a single-file
upload directly tied to a target node. Used when the user wants to
attach a file without writing a comment.
"""
import filetype
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


# ---------------------------------------------------------------------------
# Magic-byte / content-type validation
# ---------------------------------------------------------------------------
#
# Why this exists: a renamed payload (e.g. evil.exe -> report.pdf) passes
# the extension check today. The post-demo client requirement is to block
# executables even when the filename lies. We solve this by reading the
# first ~262 bytes of the upload and inspecting the file format's magic
# signature, then cross-referencing against the declared extension.

# Maps the declared extension (lowercase, no dot) -> set of MIME types
# that the magic-byte sniffer (`filetype.guess`) is allowed to detect for
# that extension. ZIP-based document formats (docx, xlsx) all surface as
# application/zip when sniffed because they ARE zip containers.
_EXT_TO_ALLOWED_MIMES: dict[str, set[str]] = {
    "pdf":  {"application/pdf"},
    "docx": {"application/zip",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xlsx": {"application/zip",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "jpg":  {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png":  {"image/png"},
    "heic": {"image/heic", "image/heif"},
    "mp4":  {"video/mp4"},
    "webm": {"video/webm"},
    "mov":  {"video/quicktime"},
}

# Extensions for which `filetype.guess` will return None because the file
# has no binary signature (it's plain text). For these we trust the
# extension after a "looks like text" sanity check (no NUL bytes + no
# executable header in the first chunk).
_TEXT_EXTENSIONS = {"txt", "csv"}

# Magic prefixes for native executables we never want to accept regardless
# of declared extension. Catches Windows PE (.exe / .dll), Linux ELF, and
# macOS Mach-O (both endiannesses + universal binaries).
_EXEC_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"MZ",            # Windows PE (exe, dll)
    b"\x7fELF",       # Linux ELF
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit BE
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit BE
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit LE
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit LE
    b"\xca\xfe\xba\xbe",  # Mach-O universal (fat) binary
)


def _looks_like_executable(buf: bytes) -> bool:
    """True if the first bytes match any native-executable magic signature."""
    return any(buf.startswith(prefix) for prefix in _EXEC_MAGIC_PREFIXES)


def _looks_like_text(buf: bytes) -> bool:
    """Heuristic: first chunk has no NUL bytes (binaries usually have NULs
    very early; legitimate text files do not)."""
    return b"\x00" not in buf


def _validate_content_matches_extension(
    buf: bytes, ext: str,
) -> tuple[bool, str | None]:
    """Sniff magic bytes and compare against the declared extension.

    Returns (is_valid, error_message). On success error_message is None.
    """
    # Universal block: native executables, regardless of extension.
    if _looks_like_executable(buf):
        return False, (
            "Executable files are not allowed. The uploaded file's "
            "content matches a native executable signature."
        )

    if ext in _TEXT_EXTENSIONS:
        # Plain-text: filetype can't sniff it. Require text-ish content.
        if not _looks_like_text(buf):
            return False, (
                f"File declared as .{ext} but content does not appear "
                f"to be plain text."
            )
        return True, None

    allowed_mimes = _EXT_TO_ALLOWED_MIMES.get(ext)
    if allowed_mimes is None:
        # Extension is in the whitelist (already checked) but we have no
        # magic-byte rule for it. Fail closed — better to reject and
        # extend the map than silently accept an unverifiable upload.
        return False, (
            f"File extension '.{ext}' is allowed but has no content "
            f"validation rule. Contact the administrator."
        )

    detected = filetype.guess(buf)
    if detected is None:
        return False, (
            f"Unable to determine file type from content. The file "
            f"declared as .{ext} may be corrupted or not a real "
            f"{ext.upper()} file."
        )

    if detected.mime not in allowed_mimes:
        return False, (
            f"File content does not match its extension. Declared as "
            f".{ext}, but content was detected as '{detected.mime}'."
        )

    return True, None


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

    # Magic-byte / content-type validation.
    # Reads the first 262 bytes (filetype's recommended buffer size) to
    # detect format from binary signature, then cross-checks against the
    # declared extension. This catches `evil.exe` renamed to `report.pdf`
    # — extension passes, content sniff fails. See module-level docstring
    # in this file for the rule matrix.
    sniff_buf = upload.file.read(262)
    upload.file.seek(0)
    is_valid, content_err = _validate_content_matches_extension(sniff_buf, ext)
    if not is_valid:
        return ServiceResult.fail(
            error=content_err,
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
