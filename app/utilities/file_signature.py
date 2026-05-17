"""Magic-byte content sniffing for uploads.

Ported from monolith's ``app/shared/file_signature.py``. Closes the
disguise vector where ``evil.exe`` is renamed ``evil.pdf`` and uploaded:
the extension-only allowlist used by ``pre_validate_files`` would have
let it pass because it only checks the trailing ``.pdf``.

Reads the first ~4 KB, runs ``filetype`` (pure-Python magic-byte
detector), and compares the detected MIME against an allowlist keyed by
extension. Text-style extensions (``.txt`` / ``.csv`` / ``.log`` /
``.md``) skip magic-byte detection and get a null-byte + UTF-8 guard
instead.

Public surface:
  * :func:`detect_and_verify` — read bytes, detect type, raise
    ``ValidationError`` on mismatch. Returns ``(detected_mime, ext)``.
  * :data:`ALLOWED_BY_EXT` — extension → set of permitted MIMEs.

Error messages match the monolith byte-for-byte so FE error display is
identical.
"""
from __future__ import annotations

from typing import Set, Tuple

try:
    import filetype as _filetype  # type: ignore
except ImportError:  # pragma: no cover — defensive
    _filetype = None  # type: ignore

from app.core.errors import ValidationError


_SNIFF_BYTES = 4096


# Extension → allowed-MIME map. Kept in lockstep with the
# ``ATTACHMENTS_ALLOWED_EXTENSIONS`` env var. Office documents
# (.docx / .xlsx / .pptx) are ZIP archives — accept either the
# Office-specific MIME or ``application/zip``.
ALLOWED_BY_EXT: dict[str, Set[str]] = {
    "pdf":  {"application/pdf"},
    "doc":  {"application/msword"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    "xls":  {"application/vnd.ms-excel"},
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    },
    "ppt":  {"application/vnd.ms-powerpoint"},
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
    },
    "jpg":  {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png":  {"image/png"},
    "gif":  {"image/gif"},
    "webp": {"image/webp"},
    # Video (matches our default ATTACHMENTS_ALLOWED_EXTENSIONS list).
    "mp4":  {"video/mp4"},
    "webm": {"video/webm"},
    "mov":  {"video/quicktime"},
    # heic.
    "heic": {"image/heic", "image/heif"},
}


_TEXT_EXTENSIONS: Set[str] = {"txt", "csv", "log", "md"}


def detect_and_verify(file_obj, filename: str) -> Tuple[str, str]:
    """Read the head of ``file_obj``, detect type, verify against
    declared extension. Returns ``(detected_mime, canonical_extension)``.

    Raises ``ValidationError`` (HTTP 422) on:
      * empty file
      * binary whose magic bytes don't match a known signature
      * binary whose detected MIME isn't in the allow-list for its ext
      * text-style file with null bytes or invalid UTF-8 in the head

    Rewinds the stream before returning so storage reads from byte 0.
    """
    ext = _safe_extension(filename)
    head, total_size = _read_head_and_rewind(file_obj)
    if total_size == 0:
        raise ValidationError(f"File '{filename}' appears to be empty.")

    if ext in _TEXT_EXTENSIONS:
        _verify_text_payload(filename, head)
        return "text/plain", ext

    if ext not in ALLOWED_BY_EXT:
        # Defensive — the broader extension allow-list upstream usually
        # rejects this first, but keep the guard local in case a caller
        # forgets to gate.
        raise ValidationError(
            f"File '{filename}' has an extension that is not recognised "
            f"for content verification."
        )

    if _filetype is None:
        # filetype lib not installed — bail rather than silently passing
        # disguised binaries through. Operator should install it.
        raise ValidationError(
            "Server is missing the file-signature library — uploads are "
            "temporarily refused. Install ``filetype`` and retry."
        )

    kind = _filetype.guess(head)
    if kind is None:
        raise ValidationError(
            f"File '{filename}' content could not be recognised. "
            f"Expected a {ext.upper()} file but the binary signature is "
            f"unknown — refusing the upload as a safety measure."
        )

    detected_mime = kind.mime
    if detected_mime not in ALLOWED_BY_EXT[ext]:
        raise ValidationError(
            f"File '{filename}' content does not match its '.{ext}' "
            f"extension. Detected type: {detected_mime}."
        )
    return detected_mime, ext


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _safe_extension(filename: str) -> str:
    if not filename:
        return ""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


def _read_head_and_rewind(file_obj) -> Tuple[bytes, int]:
    """Return ``(head_bytes, total_size)`` and leave the stream at byte 0."""
    try:
        file_obj.seek(0, 2)
        total_size = file_obj.tell()
        file_obj.seek(0)
        head = file_obj.read(_SNIFF_BYTES)
        file_obj.seek(0)
    except (AttributeError, ValueError):
        raise ValidationError(
            "Upload could not be inspected (stream not seekable). "
            "Retry the upload."
        )
    return head, total_size


def _verify_text_payload(filename: str, head: bytes) -> None:
    """Reject text uploads that contain null bytes or aren't valid UTF-8."""
    if b"\x00" in head:
        raise ValidationError(
            f"File '{filename}' is declared as a text file but contains "
            f"binary data (null bytes detected). Refusing the upload."
        )
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError(
            f"File '{filename}' is declared as a text file but is not "
            f"valid UTF-8. Refusing the upload."
        )
