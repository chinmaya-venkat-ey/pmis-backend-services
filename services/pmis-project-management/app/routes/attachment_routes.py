"""Attachment upload + dev-fallback download routes (Doc-35 send-event).

This module exposes two routers:

  - ``router`` — mounted under ``/project`` by ``app.routes.__init__``.
    Endpoint: ``POST /project/attachments/upload``.
      * Multipart, one or more files (form field ``files``).
      * Gated by ``ATTACHMENTS_CREATE``.
      * Validates per-file size (``settings.attachments_max_bytes``) and
        extension (``settings.attachments_allowed_extensions``).
      * For each file, writes bytes via ``get_file_client().upload(...)``
        and emits a ``StoredFile`` -> the JSON envelope
        ``{url, filename, mimeType, sizeBytes, uploadedAt}`` that the
        comment-create endpoint already accepts in
        ``CommentCreateRequest.attachments``.
      * On any upload failure mid-batch we best-effort delete the files
        already written so we don't leak orphaned bytes.

  - ``files_router`` — mounted at the app root (not under ``/project``)
    by ``app.main``. Endpoint: ``GET /files/{storage_key:path}``.
      * Dev-only fallback used when ``settings.file_server_public_base_url``
        is empty. In prod the static files are served by the NFS server's
        HTTP front (10.1.131.199) and this route is unused.
      * Gated by ``ATTACHMENTS_DOWNLOAD``.
      * Path-traversal-safe via ``FileStorage.absolute_path()`` which has
        a ``relative_to()`` check.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.config import settings
from app.core.errors import (
    AttachmentDisallowedExtensionError,
    AttachmentTooLargeError,
    StorageUnavailableError,
)
from app.core.permissions import ATTACHMENTS_CREATE, ATTACHMENTS_DOWNLOAD
from app.core.rbac import require_permission
from app.utilities.file_client import StoredFile, get_file_client
from app.utilities.file_storage import (
    StorageError,
    file_extension,
    get_storage,
)
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Router 1 — POST /project/attachments/upload
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/attachments", tags=["attachments"])


def _allowed_extensions() -> set[str]:
    return {
        ext.strip().lower()
        for ext in (settings.attachments_allowed_extensions or "").split(",")
        if ext.strip()
    }


def _validate_extension(filename: str, allowed: set[str]) -> None:
    """Raise ``AttachmentDisallowedExtensionError`` when ``filename`` has
    an extension not in ``allowed`` (and the allow-list is non-empty)."""
    if not allowed:
        return
    ext = file_extension(filename)
    if not ext:
        # Empty extension: treat as disallowed when the allow-list is set.
        raise AttachmentDisallowedExtensionError(
            f"Attachment {filename!r} has no extension; not allowed",
            details={"filename": filename, "allowed": sorted(allowed)},
        )
    if ext not in allowed:
        raise AttachmentDisallowedExtensionError(
            f"Attachment extension {ext!r} not allowed",
            details={"filename": filename, "allowed": sorted(allowed)},
        )


def _peek_size(upload: UploadFile) -> int:
    """Return the size of ``upload`` in bytes without consuming the stream.

    FastAPI's ``UploadFile`` wraps a ``SpooledTemporaryFile`` so we can
    seek to end / back to start cheaply. We deliberately don't read the
    bytes here — ``FileStorage.save`` streams them through 64 KB chunks.
    """
    f = upload.file
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size


def _stored_to_envelope(stored: StoredFile) -> Dict[str, Any]:
    """Map ``StoredFile`` -> the JSON shape ``CommentCreateRequest.attachments``
    accepts (camelCase, ISO-8601 timestamp)."""
    return {
        "url": stored.url,
        "filename": stored.filename,
        "mimeType": stored.mime_type,
        "sizeBytes": stored.size_bytes,
        "uploadedAt": stored.uploaded_at.isoformat(),
    }


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more attachments and return URL envelopes",
    description=(
        "Multipart upload. The response is a JSON array of "
        "``{url, filename, mimeType, sizeBytes, uploadedAt}`` envelopes "
        "ready to send back as ``CommentCreateRequest.attachments`` on "
        "``POST /project/<kind>/{id}/comments/create``. The BE never "
        "streams these bytes back — the FE fetches them from the URL "
        "directly (in prod from the NFS-fronted HTTP server; in dev "
        "from the ``GET /files/{key}`` fallback route)."
    ),
    dependencies=[Depends(require_permission(ATTACHMENTS_CREATE))],
    responses={
        409: {"description": "Attachment too large or extension disallowed"},
        503: {"description": "Storage backend (NFS / file server) unavailable"},
    },
)
async def upload_attachments(
    files: List[UploadFile] = File(..., description="One or more files."),
) -> List[Dict[str, Any]]:
    if not files:
        # Pydantic / FastAPI usually catch this, but if the form arrives
        # empty we surface a clean 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one file is required.",
        )

    max_bytes = settings.attachments_max_bytes
    allowed = _allowed_extensions()
    client = get_file_client()

    # Pre-validate all files before writing any. Avoids the case where
    # file 1 saves, file 2 fails validation, and we have to roll back
    # bytes we just wrote.
    for upload in files:
        name = upload.filename or "unnamed"
        size = _peek_size(upload)
        if size > max_bytes:
            raise AttachmentTooLargeError(
                f"Attachment {name!r} exceeds max size ({max_bytes} bytes)",
                details={
                    "filename": name,
                    "size_bytes": size,
                    "max_bytes": max_bytes,
                },
            )
        _validate_extension(name, allowed)

    # All files passed validation — now write.
    written: List[StoredFile] = []
    try:
        for upload in files:
            stored = client.upload(
                file_obj=upload.file,
                original_filename=upload.filename or "unnamed",
                mime_type=upload.content_type or "application/octet-stream",
            )
            written.append(stored)
    except StorageUnavailableError:
        # Roll back any successful writes from this batch so the disk
        # doesn't accumulate orphaned bytes.
        for s in written:
            try:
                client.delete(s.storage_key)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.warning(
                    "Failed to clean up partial upload %s after error",
                    s.storage_key,
                )
        raise

    logger.info(
        "Uploaded %d attachment(s) via %s",
        len(written), type(client).__name__,
    )
    return [_stored_to_envelope(s) for s in written]


# ---------------------------------------------------------------------------
# Router 2 — GET /files/{key} (dev fallback, mounted at app root)
# ---------------------------------------------------------------------------
files_router = APIRouter(tags=["attachments"])


@files_router.get(
    "/files/{storage_key:path}",
    summary="Serve attachment bytes from local storage (dev fallback)",
    description=(
        "Dev-only fallback so local environments don't need to deploy "
        "an nginx front. In prod ``settings.file_server_public_base_url`` "
        "is set, the comment row's URL points at the NFS server's HTTP "
        "front (10.1.131.199), and this route is never hit."
    ),
    dependencies=[Depends(require_permission(ATTACHMENTS_DOWNLOAD))],
    responses={
        404: {"description": "File not found on disk"},
        503: {"description": "Storage backend (NFS) unavailable"},
    },
)
def download_file(storage_key: str):
    storage = get_storage()
    try:
        absolute = storage.absolute_path(storage_key)
    except StorageError:
        # Path-traversal attempt or invalid key — 404 to avoid leaking
        # whether the base path exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    if not absolute.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    # Use the file's basename as the served filename. FileResponse sets
    # Content-Disposition: inline by default which is fine for the FE.
    return FileResponse(path=str(absolute), filename=absolute.name)
