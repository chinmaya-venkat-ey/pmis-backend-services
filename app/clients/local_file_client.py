"""Local-disk file client — NFS / dev fallback when pmis-file-store is unset.

Mirrors the pattern in pmis-project-management/app/utilities/file_client.py
(``LocalAndPublicUrlClient``). Bytes are written under
``settings.file_server_local_dir`` and exposed as
``{file_server_public_base_url}/{storage_key}`` — or just the bare
relative storage key when no public base is configured.

The class implements the same public surface as ``FileStoreClient``
(``upload``, ``refresh_url``, ``delete``) so the rest of the codebase
doesn't need to know which backend is in play.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional
from uuid import uuid4

from app.clients.file_store_client import (
    FileStoreUnavailable,
    RefreshedUrl,
    StoredFile,
)
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# Characters we replace in filenames before persisting — anything outside
# this set is collapsed to a hyphen. Avoids path-traversal (no slashes,
# no dots-only names, no NUL bytes).
_SAFE_FILENAME_SUBSTITUTE = "-"


def _sanitise(name: str) -> str:
    cleaned = []
    for ch in (name or "unnamed").strip():
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            cleaned.append(ch)
        else:
            cleaned.append(_SAFE_FILENAME_SUBSTITUTE)
    out = "".join(cleaned).strip(" .") or "unnamed"
    # Cap absurdly long names.
    return out[:200]


class LocalFileClient:
    """Writes bytes to a local/NFS directory and returns a URL.

    Constructed with:
      local_dir         directory the bytes land in. Created if missing.
      public_base_url   URL prefix served over local_dir (empty in dev).
      default_folder    sub-folder of local_dir for grouping (e.g.
                        "sla-attachments"). Matches the filestore client's
                        folder semantics.
    """

    def __init__(
        self,
        local_dir: str,
        public_base_url: Optional[str] = None,
        default_folder: str = "sla-attachments",
    ):
        self._local_dir = Path(local_dir).expanduser().resolve()
        self._public_base = (public_base_url or "").rstrip("/")
        self._folder = default_folder.strip("/") or "sla-attachments"
        # Create the root folder up-front so the first upload doesn't fail
        # with a confusing ENOENT.
        try:
            (self._local_dir / self._folder).mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover — defensive
            logger.warning(
                "LocalFileClient could not create %s: %s",
                self._local_dir / self._folder, exc,
            )

    # ------------------------------------------------------------------ helpers

    def _storage_key(self, original_filename: str, folder: Optional[str]) -> str:
        safe = _sanitise(original_filename)
        sub = (folder or self._folder).strip("/") or self._folder
        # UUID prefix prevents collisions when the same filename is
        # uploaded twice; keeping the original name in the key makes the
        # files browsable on disk.
        return f"{sub}/{uuid4()}-{safe}"

    def _to_url(self, key: str) -> str:
        if self._public_base:
            return f"{self._public_base}/{key}"
        # No public base configured: store the relative key. A future
        # GET /files/{key} route could serve these for dev.
        return key

    # ------------------------------------------------------------------ upload

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
        *,
        entity_type: Optional[str] = None,  # noqa: ARG002 — accepted for parity
        entity_id: Optional[str] = None,    # noqa: ARG002 — with FileStoreClient
        folder: Optional[str] = None,
        bearer_token: Optional[str] = None,  # noqa: ARG002 — unused locally
    ) -> StoredFile:
        # Read in full so size is known before writing.
        file_obj.seek(0)
        content = file_obj.read()
        size = len(content)

        key = self._storage_key(original_filename, folder)
        target = self._local_dir / key
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(content)
        except OSError as exc:
            raise FileStoreUnavailable(
                f"local file write failed at {target}: {exc}"
            ) from exc

        return StoredFile(
            file_id=key,
            download_url=self._to_url(key),
            original_filename=original_filename,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=size,
            uploaded_at=datetime.now(timezone.utc),
            # Local URLs never expire — the FE can rely on them without
            # the refresh-url dance the S3 client needs.
            expires_in_seconds=None,
        )

    # ------------------------------------------------------------------ refresh

    def refresh_url(
        self, file_id: str, *, bearer_token: Optional[str] = None,  # noqa: ARG002
    ) -> RefreshedUrl:
        """Local URLs don't expire — return the same URL with no expiry."""
        return RefreshedUrl(
            download_url=self._to_url(file_id),
            expires_in_seconds=None,
        )

    # ------------------------------------------------------------------ delete

    def delete(
        self, file_id: str, *, bearer_token: Optional[str] = None,  # noqa: ARG002
    ) -> bool:
        target = self._local_dir / file_id
        try:
            if target.exists():
                os.remove(target)
            return True
        except OSError as exc:
            logger.warning("LocalFileClient delete failed for %s: %s", target, exc)
            return False
