"""Local-folder file storage backend (NFS-mount transparent).

Ported from PMIS-OpenProject/app/infrastructure/storage/file_storage.py.

The "local folder" is parameterised by ``settings.attachments_storage_base_path``:
  - In production it is an NFS mount point (10.1.131.199) wired into the
    container via ``/etc/fstab``; the OS handles the network transport
    transparently and the app sees only a folder.
  - In development it is a plain folder under the repo root.

The code path is identical either way. Switching backend (S3 / MinIO /
HTTP file-server) is a class swap behind ``get_file_client()``; no
controller / service code changes.

Public surface:
  * ``FileStorage(base_path, subdir_strategy).ensure_ready()`` — fail-fast probe.
  * ``FileStorage.is_healthy()`` — quick readiness probe.
  * ``FileStorage.generate_storage_key(original_filename)`` — collision-safe
    relative path under the base path (e.g. ``"attachments/2026/05/{uuid}_name"``).
  * ``FileStorage.absolute_path(storage_key)`` — resolves to absolute path with
    ``relative_to()`` traversal guard (belt-and-suspenders).
  * ``FileStorage.save(storage_key, source)`` — stream-write bytes.
  * ``FileStorage.delete(storage_key)`` — best-effort unlink.
  * ``FileStorage.exists(storage_key)`` / ``FileStorage.open(storage_key)``.
  * Module-level helpers: ``sanitize_filename(raw)`` / ``file_extension(name)``.

Errors map to the canonical ``StorageUnavailableError`` in ``app.core.errors``
(HTTP 503) and ``StorageError`` (local sentinel) for path-escape attempts.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Optional
from uuid import uuid4

from app.config import settings
from app.core.errors import StorageUnavailableError
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """Base class for storage-layer programming errors (e.g. path traversal).

    Not the same as ``StorageUnavailableError`` (HTTP 503 domain error in
    ``app.core.errors``); this one stays an in-process exception because the
    only way to hit it is a coding bug, not an operational fault.
    """


# ---------------------------------------------------------------------------
# Filename safety
# ---------------------------------------------------------------------------

# Reject control chars + path separators + reserved Windows chars.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Cap original-name length kept in the storage_key. The DB column also
# stores the full original_filename; this only constrains the on-disk path.
_MAX_NAME_IN_KEY = 80


def sanitize_filename(raw: str) -> str:
    """Make ``raw`` safe to use as a single path component.

    - Normalize unicode to NFC.
    - Strip path separators / control chars / Windows-reserved chars.
    - Collapse whitespace.
    - Cap length while preserving a short extension when possible.
    - Refuse empty / dot-only results (returns ``"unnamed"``).
    """
    name = unicodedata.normalize("NFC", raw or "").strip()
    name = _UNSAFE_CHARS.sub("_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    if len(name) > _MAX_NAME_IN_KEY:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            stem = stem[: _MAX_NAME_IN_KEY - len(ext) - 1]
            name = f"{stem}.{ext}"
        else:
            name = name[:_MAX_NAME_IN_KEY]
    if not name:
        name = "unnamed"
    return name


def file_extension(filename: str) -> str:
    """Return the lowercase extension without leading dot, or empty string."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


# ---------------------------------------------------------------------------
# Storage class
# ---------------------------------------------------------------------------

class FileStorage:
    """Read/write attachment files on a local filesystem path.

    "Local" includes NFS-mounted filesystems — to the app code, an NFS
    mount looks identical to a local folder. The OS handles the transport.
    """

    def __init__(
        self,
        base_path: str,
        subdir_strategy: str = "year_month",
    ):
        self._base = Path(base_path).resolve()
        self._strategy = subdir_strategy

    # ----- Lifecycle ----------------------------------------------------

    def ensure_ready(self) -> None:
        """Make sure the base path exists and is writable.

        Called once at app startup. Creates the path if it doesn't exist
        (useful for local dev). Raises ``StorageUnavailableError`` if the
        path can't be created or written to (likely an NFS mount issue
        in prod).
        """
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot create or access storage base path "
                f"'{self._base}': {e}",
            ) from e

        # Probe write access. Catches permission misconfig early.
        probe = self._base / ".storage_probe"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            raise StorageUnavailableError(
                f"Storage base path '{self._base}' is not writable: {e}",
            ) from e

        logger.info(
            "FileStorage ready at %s (strategy=%s)",
            self._base, self._strategy,
        )

    def is_healthy(self) -> bool:
        """Quick readiness probe — used by /health and middleware."""
        try:
            return self._base.is_dir() and os.access(self._base, os.W_OK)
        except OSError:
            return False

    # ----- Key / path helpers -------------------------------------------

    def generate_storage_key(self, original_filename: str) -> str:
        """Produce a unique RELATIVE path under the base path.

        Layout depends on the configured subdir strategy:
          year_month -> "attachments/2026/05/{uuid}_{name}"
          flat       -> "attachments/{uuid}_{name}"

        The uuid prevents collisions even when two users upload files
        with identical names in the same instant.
        """
        safe = sanitize_filename(original_filename)
        unique = uuid4().hex
        if self._strategy == "flat":
            return f"attachments/{unique}_{safe}"
        # default: year_month
        now = datetime.now(timezone.utc)
        return f"attachments/{now.year:04d}/{now.month:02d}/{unique}_{safe}"

    def absolute_path(self, storage_key: str) -> Path:
        """Map a storage_key (relative path) to an absolute path under base.

        Block path-escape attempts (e.g. ``"../../etc/passwd"``). Storage
        keys always come from ``generate_storage_key()`` above, but this
        is belt-and-suspenders against bugs / regressions and against the
        ``GET /files/{key}`` fallback route taking user input.
        """
        candidate = (self._base / storage_key).resolve()
        try:
            candidate.relative_to(self._base)
        except ValueError as e:
            raise StorageError(
                f"storage_key '{storage_key}' escapes the base path",
            ) from e
        return candidate

    # ----- Read / write -------------------------------------------------

    def save(self, storage_key: str, source: BinaryIO) -> int:
        """Write ``source`` (a file-like object) to ``storage_key``.

        Streams in 64 KB chunks — does not load the whole file into memory.
        Returns the number of bytes written.
        Raises ``StorageUnavailableError`` if storage is unreachable.
        """
        target = self.absolute_path(storage_key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with target.open("wb") as out:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
            return written
        except OSError as e:
            raise StorageUnavailableError(
                f"Failed to write '{storage_key}': {e}",
            ) from e

    def open(self, storage_key: str) -> BinaryIO:
        """Return a streamable file-like object for ``storage_key``.

        Caller is responsible for closing it.
        Raises ``StorageUnavailableError`` if file missing or unreadable.
        """
        path = self.absolute_path(storage_key)
        try:
            return path.open("rb")
        except FileNotFoundError as e:
            raise StorageUnavailableError(
                f"Stored file '{storage_key}' not found on disk.",
            ) from e
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot read '{storage_key}': {e}",
            ) from e

    def delete(self, storage_key: str) -> bool:
        """Delete the file at ``storage_key``.

        Returns True on success (file existed and is gone, or never existed);
        operational errors raise ``StorageUnavailableError``.
        """
        path = self.absolute_path(storage_key)
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot delete '{storage_key}': {e}",
            ) from e

    def exists(self, storage_key: str) -> bool:
        """True iff the file is present on disk."""
        try:
            return self.absolute_path(storage_key).is_file()
        except StorageError:
            return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_storage: Optional[FileStorage] = None
_storage_lock = Lock()


def get_storage() -> FileStorage:
    """Return the process-wide ``FileStorage`` instance (lazy-initialised
    from settings on first call)."""
    global _storage
    if _storage is None:
        with _storage_lock:
            if _storage is None:
                _storage = FileStorage(
                    base_path=settings.attachments_storage_base_path,
                    subdir_strategy=settings.attachments_subdir_strategy,
                )
    return _storage


def reset_storage_for_tests() -> None:
    """Clear the cached storage so tests can re-init after monkeypatching
    settings. Not for production use."""
    global _storage
    with _storage_lock:
        _storage = None
