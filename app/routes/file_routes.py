"""File CRUD + upload/download routes.

All endpoints live under /api/v3/files/*.

Upload flow:
  POST /api/v3/files/upload
    - Multipart: field "file" (the bytes) + optional form fields
      folder, entity_type, entity_id, extra_metadata (JSON string).
    - Returns upload result with a download URL valid for
      S3_PRESIGNED_URL_EXPIRES seconds (or a permanent CDN URL when
      S3_PUBLIC_URL_BASE is configured).

Search/list:
  GET  /api/v3/files/            — filtered list (see query params)
  GET  /api/v3/files/{id}        — single file metadata

Download:
  GET  /api/v3/files/{id}/download — get a fresh pre-signed URL

Delete / restore:
  DELETE /api/v3/files/{id}       — soft-delete (default) or hard-delete
  POST   /api/v3/files/{id}/restore — restore a soft-deleted file
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.permissions import FILES_ADMIN, FILES_CREATE, FILES_DELETE, FILES_READ
from app.core.rbac import require_permission
from app.controllers.file_controller import FileController
from app.db import get_db
from app.dependencies import get_current_user_id


router = APIRouter(prefix="/files", tags=["files"])


def _get_controller(db: Session = Depends(get_db)) -> FileController:
    return FileController(db)


# -------------------------------------------------------------------- upload

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file to S3",
    description=(
        "Multipart upload. Required field: `file` (binary). "
        "Optional form fields: `folder` (default: 'general'), "
        "`entity_type`, `entity_id`, `extra_metadata` (JSON string). "
        "Returns file metadata and a download URL. "
        "Requires files:create."
    ),
    dependencies=[Depends(require_permission(FILES_CREATE))],
)
def upload_file(
    request: Request,
    file: UploadFile = File(..., description="File to upload."),
    folder: str = Form(
        "general",
        description=(
            "Logical folder. Determines the S3 key prefix after the root prefix. "
            "Example: project-attachments, milestone-docs, profile-photos."
        ),
    ),
    entity_type: Optional[str] = Form(
        None,
        description="Entity kind that owns this file (project, milestone, activity, task, subtask, user).",
    ),
    entity_id: Optional[str] = Form(
        None,
        description="UUID of the owning entity.",
    ),
    extra_metadata: Optional[str] = Form(
        None,
        description="Arbitrary JSON object stored alongside the file record.",
    ),
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    metadata: Optional[dict] = None
    if extra_metadata:
        try:
            metadata = json.loads(extra_metadata)
        except (ValueError, TypeError):
            metadata = None

    return controller.upload(
        file,
        folder=folder,
        entity_type=entity_type,
        entity_id=entity_id,
        extra_metadata=metadata,
        caller_user_id=caller_user_id,
        request=request,
    )


# -------------------------------------------------------------------- search

@router.get(
    "",
    summary="Search / list files",
    description=(
        "Returns files matching the given filters, newest first. "
        "All filters are optional — omit to list all non-deleted files. "
        "Requires files:read."
    ),
    dependencies=[Depends(require_permission(FILES_READ))],
)
def search_files(
    request: Request,
    folder: Optional[str] = Query(None, description="Filter by logical folder."),
    entity_type: Optional[str] = Query(None, description="Filter by entity type."),
    entity_id: Optional[str] = Query(None, description="Filter by entity UUID."),
    uploaded_by: Optional[str] = Query(None, description="Filter by uploader user ID."),
    include_deleted: bool = Query(False, description="When true, include soft-deleted files."),
    offset: int = Query(1, ge=1, description="Page number (1-based)."),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return controller.search(
        folder=folder,
        entity_type=entity_type,
        entity_id=entity_id,
        uploaded_by=uploaded_by,
        include_deleted=include_deleted,
        offset=offset,
        page_size=page_size,
        caller_user_id=caller_user_id,
        request=request,
    )


# ------------------------------------------------------------------ get one

@router.get(
    "/{file_id}",
    summary="Get file metadata",
    description="Returns metadata for one file by UUID. 404 if not found or deleted. Requires files:read.",
    dependencies=[Depends(require_permission(FILES_READ))],
    responses={404: {"description": "File not found"}},
)
def get_file(
    file_id: str,
    controller: FileController = Depends(_get_controller),
) -> Dict[str, Any]:
    return controller.get_file(file_id)


# ----------------------------------------------------------------- download

@router.get(
    "/{file_id}/download",
    summary="Get a download URL",
    description=(
        "Returns a time-limited pre-signed S3 GET URL (or a permanent CDN URL "
        "when S3_PUBLIC_URL_BASE is configured). The caller should redirect or "
        "fetch directly from the returned URL. Requires files:read."
    ),
    dependencies=[Depends(require_permission(FILES_READ))],
    responses={404: {"description": "File not found"}},
)
def download_file(
    file_id: str,
    request: Request,
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return controller.get_download_url(file_id, request, caller_user_id)


# ------------------------------------------------------------------- delete

@router.delete(
    "/{file_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a file",
    description=(
        "Marks the file deleted (stamps deleted_at). The S3 object is "
        "preserved for retention/restore. Pass ?hard=true (requires files:admin) "
        "to permanently remove from S3 and delete the DB record. "
        "Default soft-delete requires files:delete."
    ),
    responses={404: {"description": "File not found"}},
    dependencies=[Depends(require_permission(FILES_DELETE))],
)
def delete_file(
    file_id: str,
    request: Request,
    hard: bool = Query(
        False,
        description="When true, permanently deletes from S3 (requires files:admin).",
    ),
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    from app.core.errors import ForbiddenError
    from app.core.rbac import _is_admin, _user_permissions

    if hard and not _is_admin(request) and FILES_ADMIN not in _user_permissions(request):
        raise ForbiddenError(
            "files:admin permission required for hard delete.",
            code="permission_denied",
        )

    return controller.delete(
        file_id,
        hard_delete=hard,
        caller_user_id=caller_user_id,
        request=request,
    )


# ------------------------------------------------------------------ restore

@router.post(
    "/{file_id}/restore",
    summary="Restore a soft-deleted file",
    description=(
        "Clears deleted_at on the DB record. The S3 object was never removed "
        "on soft-delete, so the file is immediately accessible again. "
        "Requires files:delete."
    ),
    dependencies=[Depends(require_permission(FILES_DELETE))],
    responses={404: {"description": "File not found or not deleted"}},
)
def restore_file(
    file_id: str,
    request: Request,
    controller: FileController = Depends(_get_controller),
    caller_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return controller.restore(file_id, caller_user_id=caller_user_id, request=request)
