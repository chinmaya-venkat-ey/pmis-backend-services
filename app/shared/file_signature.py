"""Magic-byte content sniffing for file uploads.

Closes the disguise vector where an attacker renames ``evil.exe``
to ``evil.pdf`` and uploads it: the extension-only allowlist that
gates every upload today (``pre_validate_files``,
``comments/services/create``, ``attachments/services/upload``) would
have accepted such a file because it only checked the trailing
``.pdf`` of the filename — never the bytes.

This helper reads the first ~4 KB of the upload, runs the
``filetype`` library (pure-Python magic-byte detector), and
compares the detected MIME against an allowlist keyed by extension.
Text-style extensions (``.txt`` / ``.csv`` / ``.log`` / ``.md``) have
no signature; for those a separate guard rejects null-byte
contamination + invalid UTF-8.

Public surface:

  * :func:`detect_and_verify` — read bytes, detect type, raise
    ``ValidationError`` on mismatch. Returns the canonical sniffed
    MIME so the caller can persist that (not the client-declared
    ``upload.content_type``, which is spoofable).

  * :data:`ALLOWED_BY_EXT` — extension → set of MIME types that may
    legitimately appear under that extension. Kept here as the
    single source of truth.

Filetype reference: https://pypi.org/project/filetype/
"""
from __future__ import annotations

from typing import Optional, Set, Tuple

import filetype

from ..core.errors import ValidationError


# Read this many bytes from the file head for signature detection.
# ``filetype`` only needs ~261 bytes for its widest signature (TAR),
# but we pull 4 KB to leave headroom for the text-file null-byte +
# UTF-8 guard below.
_SNIFF_BYTES = 4096


# ---------------------------------------------------------------------------
# Extension → allowed-MIME map. Kept in lockstep with the
# ATTACHMENTS_ALLOWED_EXTENSIONS env var (settings.py).
# ---------------------------------------------------------------------------
# Office docs (.docx/.xlsx/.pptx) are ZIP archives under the hood;
# ``filetype`` detects them as ``application/zip`` rather than the
# Office-specific MIME. Allow both so legitimate docs pass while
# obviously-wrong content (PE, ELF, plain text) still fails.
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
    # Additional formats project-service supports (post-demo client
    # requirement — onsite photo / video evidence on M/A/T/S rows).
    "heic": {"image/heic", "image/heif"},
    "mp4":  {"video/mp4"},
    "webm": {"video/webm"},
    "mov":  {"video/quicktime"},
}

# Extensions that have no magic-byte signature — treated as plain text.
# Handled via the null-byte + UTF-8 guard in :func:`_verify_text_payload`.
_TEXT_EXTENSIONS: Set[str] = {"txt", "csv", "log", "md"}


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def detect_and_verify(
    file_obj,
    filename: str,
) -> Tuple[str, str]:
    """Read the head of ``file_obj``, detect its actual type, and
    verify it matches the file's declared extension.

    Returns ``(detected_mime, canonical_extension)`` on success.
    Raises ``ValidationError`` (caller maps to 422) on:

      * empty file
      * binary file whose magic bytes don't match a known signature
      * binary file whose detected MIME is not in the allowlist for
        the declared extension
      * text-style file (``.txt`` / ``.csv`` / ``.log`` / ``.md``)
        containing null bytes or invalid UTF-8 in the head

    The function reads at most :data:`_SNIFF_BYTES` from the head and
    **rewinds** the stream before returning so downstream storage
    code can read from byte 0 again.
    """
    ext = _safe_extension(filename)
    head, total_size = _read_head_and_rewind(file_obj)
    if total_size == 0:
        raise ValidationError(
            f"File '{filename}' appears to be empty.",
        )

    # Text-style extension: skip magic-byte detection (there's no
    # signature), apply the binary-rejection guard instead.
    if ext in _TEXT_EXTENSIONS:
        _verify_text_payload(filename, head, ext)
        # Caller persists ``text/plain`` for text-style uploads —
        # neutral, accurate, and prevents the browser from being
        # tricked by a spoofed content_type.
        return "text/plain", ext

    # Binary-style extension. Must be on the allowlist AND filetype
    # must detect it as one of the accepted MIMEs.
    if ext not in ALLOWED_BY_EXT:
        # This branch is theoretically dead — the extension-allowlist
        # check upstream rejects anything not on the broader list —
        # but kept defensively in case a caller forgets to gate.
        raise ValidationError(
            f"File '{filename}' has an extension that is not "
            f"recognised for content verification.",
        )

    kind = filetype.guess(head)
    if kind is None:
        raise ValidationError(
            f"File '{filename}' content could not be recognised. "
            f"Expected a {ext.upper()} file but the binary signature "
            f"is unknown — refusing the upload as a safety measure.",
        )

    detected_mime = kind.mime
    allowed = ALLOWED_BY_EXT[ext]
    if detected_mime not in allowed:
        raise ValidationError(
            f"File '{filename}' content does not match its '.{ext}' "
            f"extension. Detected type: {detected_mime}.",
        )
    return detected_mime, ext


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _safe_extension(filename: str) -> str:
    """Lowercase, dot-stripped extension. Returns '' for filenames
    with no dot."""
    if not filename:
        return ""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip().lower()


def _read_head_and_rewind(file_obj) -> Tuple[bytes, int]:
    """Return ``(head_bytes, total_size_bytes)``. Rewinds the stream
    before returning so downstream storage reads from byte 0.

    ``file_obj`` is the ``SpooledTemporaryFile`` underneath FastAPI's
    ``UploadFile`` — supports ``seek`` + ``tell`` + ``read``.
    """
    try:
        file_obj.seek(0, 2)
        total_size = file_obj.tell()
        file_obj.seek(0)
        head = file_obj.read(_SNIFF_BYTES)
        file_obj.seek(0)
    except (AttributeError, ValueError):
        # Defensive — if the upload object doesn't support seek (e.g.
        # an unusual test double), refuse rather than guess.
        raise ValidationError(
            "Upload could not be inspected (stream not seekable). "
            "Retry the upload."
        )
    return head, total_size


def _verify_text_payload(filename: str, head: bytes, ext: str) -> None:
    """Reject text uploads that contain null bytes or aren't valid
    UTF-8. Catches the case where an attacker renames a binary to
    ``.txt`` / ``.csv`` / ``.log`` / ``.md``.

    Plain text never contains NULL bytes; every Windows / Linux /
    macOS executable has them early in the header. UTF-8 decode
    failure is a second line of defence for binaries that happen to
    avoid NULLs in the first 4 KB.
    """
    if b"\x00" in head:
        raise ValidationError(
            f"File '{filename}' is declared as a text file but "
            f"contains binary data (null bytes detected). Refusing "
            f"the upload."
        )
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError(
            f"File '{filename}' is declared as a text file but is "
            f"not valid UTF-8. Refusing the upload."
        )
