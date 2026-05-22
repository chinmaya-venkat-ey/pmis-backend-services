"""MIME type detection via content sniffing (filetype lib) with
filename-extension fallback.

Adapted from PMIS-project-management. No NFS dependency.
"""
from __future__ import annotations

import mimetypes
from typing import Optional


def detect_mime(content: bytes, filename: str = "") -> Optional[str]:
    """Return the MIME type for the given content bytes.

    Tries content-sniffing first (reliable for binary formats).
    Falls back to filename extension lookup (covers text formats
    like .csv, .txt that don't have magic bytes).
    """
    try:
        import filetype as _ft
        kind = _ft.guess(content)
        if kind is not None:
            return kind.mime
    except Exception:  # noqa: BLE001
        pass

    if filename:
        mime, _ = mimetypes.guess_type(filename)
        if mime:
            return mime

    return "application/octet-stream"
