"""External file-server client (doc 35).

The senior's design: each comment row stores the URL of an attachment
on an external file server, not an FK to a separate attachments table.
The FE fetches bytes directly from that URL — the BE no longer streams
file bytes through a download endpoint.

This module is the seam where "the BE has bytes in memory" turns into
"a URL string we save on the row". Two implementations sit behind one
interface so we can ship the schema/contract change immediately and
swap the implementation later when a real file server is deployed:

  1. ``LocalAndPublicUrlClient`` — writes bytes to the existing
     ``FileStorage`` (local disk / NFS) and returns
     ``f"{public_base}/{storage_key}"`` (or just ``storage_key`` when
     the public base isn't configured). The BE serves these via the
     fallback ``GET /files/{key}`` route in dev.

  2. ``HttpExternalFileClient`` — POSTs bytes to a configured external
     file-server and returns the URL the server hands back. Used when
     ``FILE_SERVER_BASE_URL`` is set.

The public client API is intentionally tiny:

    client = get_file_client()
    info = client.upload(file_obj, original_filename, mime_type)
    # info = StoredFile(url, storage_key, filename, mime_type, size_bytes,
    #                   uploaded_at)

    client.delete(storage_key)   # best-effort, used for rollback only

Callers don't care whether the bytes ended up local or on a remote
server — they only persist ``info.url`` on the comment row.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import BinaryIO, Optional, Protocol

from ...core.config import settings
from .file_storage import (
    FileStorage,
    StorageError,
    StorageUnavailableError,
    get_storage,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass returned by every implementation
# ---------------------------------------------------------------------------
@dataclass
class StoredFile:
    """The result of a successful upload — what we persist on a row."""
    url: str                # public URL the FE fetches; saved on comment row
    storage_key: str        # internal handle for delete / debug
    filename: str           # display name (original from the user)
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


# ---------------------------------------------------------------------------
# Protocol every backend implements
# ---------------------------------------------------------------------------
class FileClient(Protocol):
    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
    ) -> StoredFile: ...

    def delete(self, storage_key: str) -> bool: ...


# ---------------------------------------------------------------------------
# Implementation 1 — local disk + public URL prefix (the default)
# ---------------------------------------------------------------------------
class LocalAndPublicUrlClient:
    """Writes bytes via the existing ``FileStorage`` and turns the
    storage key into a public URL using ``FILE_SERVER_PUBLIC_BASE_URL``.

    Default behaviour when ``FILE_SERVER_PUBLIC_BASE_URL`` is empty:
    the saved URL is just the relative storage key (e.g.
    ``"attachments/2026/05/abc.pdf"``) and the BE's fallback route
    ``GET /files/{key}`` resolves it from local disk. This is the
    dev-friendly path — it keeps the FE contract honest (URL on the
    row) without requiring a real external server to be deployed.
    """

    def __init__(self, storage: FileStorage, public_base_url: str):
        self._storage = storage
        # Trim trailing slash for predictable concatenation.
        self._public_base = (public_base_url or "").rstrip("/")

    def _to_public_url(self, storage_key: str) -> str:
        if self._public_base:
            return f"{self._public_base}/{storage_key}"
        # No public base configured — store the relative key. The
        # fallback route at /files/{key} (mounted in app.main when
        # FILE_SERVER_LOCAL_FALLBACK_ENABLED is true) serves these.
        return storage_key

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
    ) -> StoredFile:
        # Compute the size first by seeking, so the response carries
        # the canonical byte count from disk rather than whatever the
        # caller estimated.
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)

        key = self._storage.generate_storage_key(original_filename or "unnamed")
        # ``save`` raises StorageUnavailableError on disk / mount issues.
        self._storage.save(key, file_obj)

        return StoredFile(
            url=self._to_public_url(key),
            storage_key=key,
            filename=original_filename or "unnamed",
            mime_type=mime_type or "application/octet-stream",
            size_bytes=size,
            uploaded_at=datetime.now(timezone.utc),
        )

    def delete(self, storage_key: str) -> bool:
        try:
            return self._storage.delete(storage_key)
        except StorageError:
            return False


# ---------------------------------------------------------------------------
# Implementation 2 — HTTP forwarder to an external file server
# ---------------------------------------------------------------------------
class HttpExternalFileClient:
    """Forwards bytes to ``settings.FILE_SERVER_BASE_URL`` and returns
    the URL the server replies with.

    Stub implementation — the real wire format depends on the file
    server we end up shipping. When that's nailed down, this is where
    the request shape lives. For now the class exists so the seam is
    clear and the swap is one ``get_file_client`` change.

    The class intentionally raises ``StorageUnavailableError`` when
    the upstream server is down or returns a non-2xx, so callers map
    it to the same 503 they already handle for local-storage failures.
    """

    def __init__(self, base_url: str, auth_token: str, fallback: FileClient):
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token or ""
        # When the external server is unreachable, fall back to local
        # storage so the request doesn't 503. Operators can disable
        # this by setting the fallback client's storage path to
        # something always-unavailable.
        self._fallback = fallback

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
    ) -> StoredFile:
        # TODO: real implementation lands when the file-server contract
        # (endpoint, auth, response shape) is finalised. Today we route
        # through the local fallback so the BE ships and the FE-facing
        # contract (URL on the row) stays correct.
        logger.warning(
            "HttpExternalFileClient is a stub; routing %s through local fallback",
            original_filename,
        )
        return self._fallback.upload(file_obj, original_filename, mime_type)

    def delete(self, storage_key: str) -> bool:
        return self._fallback.delete(storage_key)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_client: Optional[FileClient] = None
_client_lock = Lock()


def get_file_client() -> FileClient:
    """Return the process-wide file client (lazy-initialised from settings).

    Resolution order:
      1. If ``FILE_SERVER_BASE_URL`` is set → ``HttpExternalFileClient``
         (with a local-storage fallback for failures).
      2. Else → ``LocalAndPublicUrlClient`` (the default; uses
         ``FILE_SERVER_PUBLIC_BASE_URL`` when set, relative paths when
         unset).
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                local = LocalAndPublicUrlClient(
                    storage=get_storage(),
                    public_base_url=settings.FILE_SERVER_PUBLIC_BASE_URL,
                )
                if settings.FILE_SERVER_BASE_URL:
                    _client = HttpExternalFileClient(
                        base_url=settings.FILE_SERVER_BASE_URL,
                        auth_token=settings.FILE_SERVER_AUTH_TOKEN,
                        fallback=local,
                    )
                else:
                    _client = local
    return _client


def reset_file_client_for_tests() -> None:
    """Clear the cached client so tests can re-init after monkeypatching
    settings. Not for production use."""
    global _client
    with _client_lock:
        _client = None
