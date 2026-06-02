"""External file-server client (Doc-35 send-event seam).

Ported from PMIS-OpenProject/app/infrastructure/storage/external_file_client.py.

After Doc-35 each comment row stores a *URL* of its attachment, not an
FK into a separate ``attachments`` table. The FE fetches bytes directly
from that URL — the BE no longer streams bytes through a download
endpoint.

This module is the seam where "the BE has bytes in memory" turns into
"a URL string we save on the row". Two implementations sit behind one
``FileClient`` protocol so we can ship the schema/contract change today
and swap implementations later when a dedicated file server is deployed:

  1. ``LocalAndPublicUrlClient`` — writes bytes through the existing
     ``FileStorage`` (NFS-mounted folder in prod, local folder in dev)
     and returns ``f"{public_base}/{storage_key}"`` when
     ``settings.file_server_public_base_url`` is set, or the bare
     ``storage_key`` otherwise (served by the ``GET /files/{key}``
     fallback route at app root).

  2. ``HttpExternalFileClient`` — stub that *would* POST bytes to a
     configured external file-server (``settings.file_server_base_url``);
     today it transparently falls back to ``LocalAndPublicUrlClient`` so
     the BE wire-contract (URL on the row) ships intact.

Public client API (intentionally tiny):

    client = get_file_client()
    info = client.upload(file_obj, original_filename, mime_type)
    # info = StoredFile(url, storage_key, filename, mime_type, size_bytes,
    #                   uploaded_at)
    client.delete(storage_key)   # best-effort, used for rollback only

Callers don't care whether the bytes landed local or on a remote
server — they only persist ``info.url`` on the comment row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import BinaryIO, Optional, Protocol

from app.config import settings
from app.utilities.file_storage import (
    FileStorage,
    StorageError,
    get_storage,
)
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass returned by every implementation
# ---------------------------------------------------------------------------
@dataclass
class StoredFile:
    """The result of a successful upload — what we persist on a row.

    The route layer maps this dataclass to the comment-create JSON
    envelope ``{url, filename, mimeType, sizeBytes, uploadedAt}`` that
    ``CommentCreateRequest.attachments`` expects.
    """
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
    storage key into a public URL using ``settings.file_server_public_base_url``.

    Default behaviour when the public base URL is empty: the saved URL is
    just the relative storage key (e.g. ``"attachments/2026/05/abc.pdf"``)
    and the BE's fallback ``GET /files/{key}`` route resolves it from
    local disk. This is the dev-friendly path — it keeps the FE contract
    honest (URL on the row) without requiring a real external server
    to be deployed.
    """

    def __init__(self, storage: FileStorage, public_base_url: str):
        self._storage = storage
        # Trim trailing slash for predictable concatenation.
        self._public_base = (public_base_url or "").rstrip("/")

    def _to_public_url(self, storage_key: str) -> str:
        if self._public_base:
            return f"{self._public_base}/{storage_key}"
        # No public base configured — store the relative key. The
        # fallback route at /files/{key} (mounted at app root in
        # app.main when file_server_local_fallback_enabled is true)
        # serves these.
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
        except Exception:  # noqa: BLE001 — best-effort rollback path
            return False


# ---------------------------------------------------------------------------
# Implementation 2 — HTTP forwarder to an external file server
# ---------------------------------------------------------------------------
class HttpExternalFileClient:
    """Forwards bytes to ``settings.file_server_base_url`` and returns
    the URL the server replies with.

    Stub implementation — the real wire format depends on the file
    server we end up shipping (PMIS prod uses NFS + nginx, so this
    branch is dormant). When a dedicated server is nailed down, this
    class is where the request shape lives. For now we route through
    the local fallback so the BE ships and the FE-facing contract
    (URL on the row) stays correct.
    """

    def __init__(self, base_url: str, auth_token: str, fallback: FileClient):
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token or ""
        # When the external server is unreachable / unimplemented, fall
        # back to local storage so the request doesn't 503.
        self._fallback = fallback

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
    ) -> StoredFile:
        # Deferred: real implementation lands when the file-server contract
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
      1. ``settings.file_store_service_url`` is set →
         ``HttpFileStoreClient`` — delegates to pmis-file-store (S3).
         This is the production path after file-svc is deployed.
      2. ``settings.file_server_base_url`` is set →
         ``HttpExternalFileClient`` (legacy external file-server stub).
      3. Default → ``LocalAndPublicUrlClient`` (NFS mount / local dev).
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                # Priority 1: pmis-file-store S3 microservice.
                if settings.file_store_service_url:
                    from app.utilities.http_file_client import HttpFileStoreClient
                    _client = HttpFileStoreClient(
                        base_url=settings.file_store_service_url,
                        token=settings.file_store_service_token or "",
                        folder=settings.file_store_default_folder,
                    )
                    logger.info(
                        "FileClient: using pmis-file-store at %s",
                        settings.file_store_service_url,
                    )
                else:
                    local = LocalAndPublicUrlClient(
                        storage=get_storage(),
                        public_base_url=settings.file_server_public_base_url or "",
                    )
                    if settings.file_server_base_url:
                        _client = HttpExternalFileClient(
                            base_url=settings.file_server_base_url,
                            auth_token=settings.file_server_auth_token or "",
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
