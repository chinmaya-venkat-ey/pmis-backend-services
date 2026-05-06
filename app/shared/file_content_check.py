"""Magic-byte / declared-extension content-validation helper.

Post-demo client requirement (project-service-only — not present in the
monolith): renamed payloads (``evil.exe`` -> ``report.pdf``) must be
rejected even if the extension is whitelisted. We read the first ~262
bytes, inspect the file format's magic signature, and cross-reference
against the declared extension.

Used by the comments + attachments upload paths.
"""
from typing import Optional, Tuple

import filetype


# Map declared extension (lowercase, no dot) -> set of MIME types that
# the magic-byte sniffer is allowed to detect for that extension.
# ZIP-based document formats (docx, xlsx) all surface as application/zip.
_EXT_TO_ALLOWED_MIMES = {
    "pdf":  {"application/pdf"},
    "docx": {
        "application/zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "xlsx": {
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "jpg":  {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png":  {"image/png"},
    "heic": {"image/heic", "image/heif"},
    "mp4":  {"video/mp4"},
    "webm": {"video/webm"},
    "mov":  {"video/quicktime"},
}

# Plain-text formats with no magic bytes — verified via "looks like text"
# heuristic instead.
_TEXT_EXTENSIONS = {"txt", "csv"}

# Magic prefixes for native executables — never accepted regardless of
# declared extension. Catches Windows PE, Linux ELF, and macOS Mach-O.
_EXEC_MAGIC_PREFIXES = (
    b"MZ",                 # Windows PE (exe, dll)
    b"\x7fELF",            # Linux ELF
    b"\xfe\xed\xfa\xce",   # Mach-O 32 BE
    b"\xfe\xed\xfa\xcf",   # Mach-O 64 BE
    b"\xce\xfa\xed\xfe",   # Mach-O 32 LE
    b"\xcf\xfa\xed\xfe",   # Mach-O 64 LE
    b"\xca\xfe\xba\xbe",   # Mach-O universal (fat) binary
)


def _looks_like_executable(buf: bytes) -> bool:
    return any(buf.startswith(prefix) for prefix in _EXEC_MAGIC_PREFIXES)


def _looks_like_text(buf: bytes) -> bool:
    return b"\x00" not in buf


def validate_content_matches_extension(
    buf: bytes, ext: str,
) -> Tuple[bool, Optional[str]]:
    """Sniff magic bytes and compare against the declared extension.

    Returns ``(is_valid, error_message)``. On success ``error_message``
    is ``None``.
    """
    if _looks_like_executable(buf):
        return False, (
            "Executable files are not allowed. The uploaded file's "
            "content matches a native executable signature."
        )

    if ext in _TEXT_EXTENSIONS:
        if not _looks_like_text(buf):
            return False, (
                f"File declared as .{ext} but content does not appear "
                f"to be plain text."
            )
        return True, None

    allowed_mimes = _EXT_TO_ALLOWED_MIMES.get(ext)
    if allowed_mimes is None:
        # Extension is whitelisted but we have no magic-byte rule for it.
        # Fail closed — better to reject than silently accept.
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
