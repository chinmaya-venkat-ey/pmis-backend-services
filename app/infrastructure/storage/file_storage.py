"""Local-folder file storage backend.

This is the single concrete implementation of the storage layer. The
"local folder" is parameterised by ``ATTACHMENTS_STORAGE_BASE_PATH`` —
in production it's an NFS mount point that the OS sets up via
``/etc/fstab``; in development it's a plain folder under the repo
root. The code path is identical either way; the app sees just a
folder.

Why this design:
- Switching storage backend is an env-var change, not a code change.
- No SDK / no external service dependency in the app process.
- The OS handles the network transfer (in the NFS case) transparently.
- A future swap to MinIO/S3 means writing a parallel class with the
  same interface; no controller / service code changes.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Optional
from uuid import uuid4

from ...core.config import settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """Base class for storage-layer errors."""


class StorageUnavailableError(StorageError):
    """Raised when the storage path is unreachable / not mounted /
    permission-denied. Controllers map this to HTTP 503."""


# ---------------------------------------------------------------------------
# Filename safety
# ---------------------------------------------------------------------------

# Reject control chars + path separators + reserved Windows chars.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Cap original-name length kept in the storage_key. The DB column also
# stores the full original_filename; this only constrains the on-disk path.
_MAX_NAME_IN_KEY = 80


def sanitize_filename(raw: str) -> str:
    """Make ``raw`` safe to use as a path component.

    - Normalize unicode to NFC.
    - Strip path separators / control chars / Windows-reserved chars.
    - Collapse whitespace.
    - Cap length.
    - Refuse empty / dot-only results.
    """
    name = unicodedata.normalize("NFC", raw or "").strip()
    name = _UNSAFE_CHARS.sub("_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    if len(name) > _MAX_NAME_IN_KEY:
        # Preserve extension if possible.
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
        (useful for local dev). Raises StorageUnavailableError if the
        path can't be created or written to (likely an NFS mount issue
        in prod).
        """
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot create or access storage base path "
                f"'{self._base}': {e}"
            ) from e

        # Probe write access. Catches permission misconfig early.
        probe = self._base / ".storage_probe"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            raise StorageUnavailableError(
                f"Storage base path '{self._base}' is not writable: {e}"
            ) from e

        logger.info("FileStorage ready at %s (strategy=%s)",
                    self._base, self._strategy)

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
          year_month → "attachments/2026/04/{uuid}_{name}"
          flat       → "attachments/{uuid}_{name}"

        The uuid prevents collisions even if two users upload files
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
        """Map a storage_key (relative path) to an absolute path under base."""
        # Block path-escape attempts (e.g. "../../etc/passwd").
        # storage_key always comes from generate_storage_key() above, but
        # this is belt-and-suspenders against bugs/regressions.
        candidate = (self._base / storage_key).resolve()
        try:
            candidate.relative_to(self._base)
        except ValueError as e:
            raise StorageError(
                f"storage_key '{storage_key}' escapes the base path"
            ) from e
        return candidate

    # ----- Read / write -------------------------------------------------

    def save(self, storage_key: str, source: BinaryIO) -> int:
        """Write ``source`` (a file-like object) to ``storage_key``.

        Streams in chunks — does not load the whole file into memory.
        Returns the number of bytes written.
        Raises StorageUnavailableError if storage is unreachable.
        """
        target = self.absolute_path(storage_key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with target.open("wb") as out:
                while True:
                    chunk = source.read(64 * 1024)  # 64 KB
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
            return written
        except OSError as e:
            raise StorageUnavailableError(
                f"Failed to write '{storage_key}': {e}"
            ) from e

    def open(self, storage_key: str) -> BinaryIO:
        """Return a streamable file-like object for ``storage_key``.

        Caller is responsible for closing it.
        Raises StorageUnavailableError if file missing or unreadable.
        """
        path = self.absolute_path(storage_key)
        try:
            return path.open("rb")
        except FileNotFoundError as e:
            raise StorageUnavailableError(
                f"Stored file '{storage_key}' not found on disk."
            ) from e
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot read '{storage_key}': {e}"
            ) from e

    def delete(self, storage_key: str) -> bool:
        """Delete the file at ``storage_key``. Returns True if it was
        deleted, False if it didn't exist. Errors raise."""
        path = self.absolute_path(storage_key)
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as e:
            raise StorageUnavailableError(
                f"Cannot delete '{storage_key}': {e}"
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
    """Return the process-wide FileStorage instance (lazy-initialised
    from settings on first call)."""
    global _storage
    if _storage is None:
        with _storage_lock:
            if _storage is None:
                _storage = FileStorage(
                    base_path=settings.ATTACHMENTS_STORAGE_BASE_PATH,
                    subdir_strategy=settings.ATTACHMENTS_SUBDIR_STRATEGY,
                )
    return _storage
