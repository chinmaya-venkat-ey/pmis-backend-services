"""HTTP client that delegates file operations to pmis-file-store.

This client implements the same ``FileClient`` protocol as
``LocalAndPublicUrlClient`` so it is a drop-in replacement. When
``settings.file_store_service_url`` is set, ``get_file_client()`` returns
this implementation instead of the NFS-backed local client.

Upload flow:
  1. POST {FILE_STORE_URL}/api/v3/files/upload   (multipart)
  2. file-svc stores in S3, returns {fileId, downloadUrl, ...}
  3. We return a ``StoredFile`` with url=downloadUrl, storage_key=fileId

Delete flow:
  1. DELETE {FILE_STORE_URL}/api/v3/files/{storage_key}
  2. file-svc soft-deletes the DB record (S3 object preserved)
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, Optional

import httpx

from app.utilities.logger import get_logger
from app.utilities.file_client import StoredFile


logger = get_logger(__name__)

# Timeout values (seconds). Upload can take longer than reads.
_UPLOAD_TIMEOUT = 120.0
_DEFAULT_TIMEOUT = 30.0


class HttpFileStoreClient:
    """Delegates uploads/deletes to pmis-file-store via HTTP.

    Constructed with:
      base_url   — e.g. "http://pmis-file-store:8005"
      token      — service-to-service JWT (bearer token)
      folder     — default logical folder for uploads
                   (can be overridden per-call via attachment metadata)
    """

    def __init__(self, base_url: str, token: str, folder: str = "project-attachments"):
        self._base = base_url.rstrip("/")
        self._token = token
        self._folder = folder

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self._token}"}
        return h

    def upload(
        self,
        file_obj: BinaryIO,
        original_filename: str,
        mime_type: str,
        *,
        folder: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> StoredFile:
        """Upload bytes to file-svc and return a StoredFile descriptor.

        Raises RuntimeError on HTTP / connection failure (caught upstream
        by AttachmentService which maps it to StorageUnavailableError).
        """
        # Seek to the start and read all content so we can send it.
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
                    headers=self._headers(),
                    files={"file": (original_filename, io.BytesIO(content), mime_type)},
                    data=data,
                )
        except httpx.RequestError as exc:
            raise RuntimeError(f"file-svc upload request failed: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"file-svc upload returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        body = resp.json()
        result = body.get("data") or body  # unwrap PMIS envelope if present

        return StoredFile(
            url=result.get("downloadUrl") or result.get("download_url") or "",
            storage_key=result.get("fileId") or result.get("file_id") or "",
            filename=original_filename,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=result.get("sizeBytes") or result.get("size_bytes") or len(content),
            uploaded_at=datetime.now(timezone.utc),
        )

    def delete(self, storage_key: str) -> bool:
        """Soft-delete the file in file-svc. Returns True on success."""
        if not storage_key:
            return False
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                resp = client.delete(
                    f"{self._base}/api/v3/files/{storage_key}",
                    headers=self._headers(),
                )
            if resp.status_code in (200, 204, 404):
                return True
            logger.warning(
                "file-svc delete returned HTTP %s for key=%s",
                resp.status_code, storage_key,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("file-svc delete failed for key=%s: %s", storage_key, exc)
            return False
