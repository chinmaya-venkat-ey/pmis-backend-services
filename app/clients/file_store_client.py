"""HTTP client for pmis-file-store (the S3 microservice).

Adapted from project-mgmt's ``HttpFileStoreClient``. The browser uploads
to *this service* (contract-management), and we forward the bytes to
pmis-file-store under our service-to-service bearer token. Filestore
returns a UUID handle (``file_id``) and a presigned download URL —
those land on ``contract.sla_attachments.file_id`` /
``contract.sla_attachments.file_url``.

The filestore endpoints we use:

  POST   /api/v3/files/upload          (multipart)
  GET    /api/v3/files/{id}/download    (fresh presigned URL)
  DELETE /api/v3/files/{id}             (soft-delete)
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, Optional

import httpx

from app.utilities.logger import get_logger


logger = get_logger(__name__)

_UPLOAD_TIMEOUT = 120.0
_DEFAULT_TIMEOUT = 30.0


class FileStoreUnavailable(RuntimeError):
    """Raised when pmis-file-store is unreachable or returns 5xx.

    The attachment route maps this to a 503 so the FE can show a
    friendly "the file service is down — try again" instead of a stack
    trace.
    """


@dataclass
class StoredFile:
    """Result of a successful upload — what we persist on the row."""
    file_id: str           # filestore UUID, canonical handle
    download_url: str      # presigned URL the FE can fetch directly
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime
    # When None, the URL doesn't expire (configured CDN base). Otherwise
    # this is the lifetime in seconds and the FE should refresh before it
    # crosses zero.
    expires_in_seconds: Optional[int] = None


@dataclass
class RefreshedUrl:
    """Result of a refresh-url call — fresh URL + new expiry."""
    download_url: str
    expires_in_seconds: Optional[int] = None


class FileStoreClient:
    """Forwards uploads/downloads/deletes to pmis-file-store.

    The class is intentionally thin: each method makes one HTTP call.
    We do not retry — the caller decides whether to surface the error
    or fall back to defaults.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        default_folder: str = "sla-attachments",
    ):
        self._base = (base_url or "").rstrip("/")
        self._token = token or ""
        self._folder = default_folder

    def _headers(self, bearer_token: Optional[str] = None) -> dict:
        # When the caller's own bearer is supplied (typical for routes
        # that already accept Authorization), prefer it so filestore can
        # see the originating user. Falls back to the service-to-service
        # token for background jobs.
        token = bearer_token or self._token
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ------------------------------------------------------------------ upload

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
        *,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        folder: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> StoredFile:
        """Forward a multipart upload to pmis-file-store.

        Raises ``FileStoreUnavailable`` on connection / 5xx errors so the
        route layer can return 503.
        """
        file_obj.seek(0)
        content = file_obj.read()

        data = {"folder": folder or self._folder}
        if entity_type:
            data["entity_type"] = entity_type
        if entity_id:
            data["entity_id"] = entity_id

        try:
            with httpx.Client(timeout=_UPLOAD_TIMEOUT) as client:
                resp = client.post(
                    f"{self._base}/api/v3/files/upload",
                    headers=self._headers(bearer_token),
                    files={"file": (original_filename, io.BytesIO(content), mime_type)},
                    data=data,
                )
        except httpx.RequestError as exc:
            raise FileStoreUnavailable(
                f"file-svc upload request failed: {exc}"
            ) from exc

        if resp.status_code >= 500:
            raise FileStoreUnavailable(
                f"file-svc upload returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        if resp.status_code not in (200, 201):
            # 4xx is a client error (e.g. unsupported MIME) — surface as a
            # plain RuntimeError so the route maps to 400.
            raise RuntimeError(
                f"file-svc upload returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )

        body = resp.json()
        # PMIS envelopes responses as ``{data: {...}}``; unwrap when present.
        result = body.get("data") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            result = body if isinstance(body, dict) else {}

        return StoredFile(
            file_id=result.get("file_id") or result.get("fileId") or "",
            download_url=(
                result.get("download_url")
                or result.get("downloadUrl")
                or result.get("public_url")
                or ""
            ),
            original_filename=(
                result.get("original_filename")
                or result.get("originalFilename")
                or original_filename
            ),
            mime_type=result.get("mime_type") or result.get("mimeType") or mime_type or "",
            size_bytes=int(
                result.get("size_bytes") or result.get("sizeBytes") or len(content)
            ),
            uploaded_at=datetime.now(timezone.utc),
            expires_in_seconds=result.get("expires_in_seconds")
            or result.get("expiresInSeconds"),
        )

    # ------------------------------------------------------------------ refresh

    def refresh_url(
        self, file_id: str, *, bearer_token: Optional[str] = None,
    ) -> RefreshedUrl:
        """Get a fresh download URL for a file already in pmis-file-store."""
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                resp = client.get(
                    f"{self._base}/api/v3/files/{file_id}/download",
                    headers=self._headers(bearer_token),
                )
        except httpx.RequestError as exc:
            raise FileStoreUnavailable(
                f"file-svc refresh-url request failed: {exc}"
            ) from exc

        if resp.status_code >= 500:
            raise FileStoreUnavailable(
                f"file-svc refresh-url returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"file-svc refresh-url returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )

        body = resp.json()
        result = body.get("data") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            result = body if isinstance(body, dict) else {}
        return RefreshedUrl(
            download_url=result.get("download_url")
            or result.get("downloadUrl")
            or "",
            expires_in_seconds=result.get("expires_in_seconds")
            or result.get("expiresInSeconds"),
        )

    # ------------------------------------------------------------------ delete

    def delete(
        self, file_id: str, *, bearer_token: Optional[str] = None,
    ) -> bool:
        """Soft-delete the file in pmis-file-store.

        Returns True on success. We swallow errors here because the
        caller (attachment service) has already removed our own row —
        a filestore failure shouldn't undo that. Logged for ops.
        """
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                resp = client.delete(
                    f"{self._base}/api/v3/files/{file_id}",
                    headers=self._headers(bearer_token),
                )
        except httpx.RequestError as exc:
            logger.warning(
                "file-svc delete failed for %s: %s", file_id, exc,
            )
            return False
        if resp.status_code >= 400:
            logger.warning(
                "file-svc delete %s returned HTTP %s: %s",
                file_id, resp.status_code, resp.text[:200],
            )
            return False
        return True
