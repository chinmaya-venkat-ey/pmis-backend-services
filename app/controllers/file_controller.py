"""FileController — thin orchestration layer between routes and FileService.

Resolves request-level context (caller IP, user agent) and shapes
service results into the wire dicts returned by HalApiRoute.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request, UploadFile
from sqlalchemy.orm import Session

from app.models.file_audit_log import FileAuditLog
from app.models.file_object import FileObject
from app.schemas.file_object import (
    FileDeleteResponse,
    FileDownloadResponse,
    FileRestoreResponse,
    FileUploadResponse,
)
from app.services.file_service import FileService
from app.utilities.s3_client import get_s3_client
from app.utilities.timezones import IST


def _ip(request: Request) -> Optional[str]:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _ua(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    from datetime import timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()


def _file_dict(row: FileObject) -> Dict[str, Any]:
    return {
        "id": row.id,
        "folder": row.folder,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "original_filename": row.original_filename,
        "s3_key": row.s3_key,
        "s3_bucket": row.s3_bucket,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "content_hash": row.content_hash,
        "public_url": row.public_url,
        "extra_metadata": row.extra_metadata,
        "uploaded_by": row.uploaded_by,
        "deleted_at": _iso(row.deleted_at),
        "deleted_by": row.deleted_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _audit_dict(row: FileAuditLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "file_id": row.file_id,
        "action": row.action,
        "actor_user_id": row.actor_user_id,
        "folder": row.folder,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "original_filename": row.original_filename,
        "extra_metadata": row.extra_metadata,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": _iso(row.created_at),
    }


class FileController:
    def __init__(self, db: Session):
        self.db = db
        self._svc = FileService(db, get_s3_client())

    def upload(
        self,
        upload: UploadFile,
        *,
        folder: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        extra_metadata: Optional[dict],
        caller_user_id: Optional[str],
        request: Request,
    ) -> Dict[str, Any]:
        row, download_url, expires = self._svc.upload(
            upload,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            extra_metadata=extra_metadata,
            actor_user_id=caller_user_id,
            ip_address=_ip(request),
            user_agent=_ua(request),
        )
        return {
            "_bare": True,
            "_type": "FileUpload",
            "fileId": row.id,
            "originalFilename": row.original_filename,
            "folder": row.folder,
            "entityType": row.entity_type,
            "entityId": row.entity_id,
            "s3Key": row.s3_key,
            "s3Bucket": row.s3_bucket,
            "mimeType": row.mime_type,
            "sizeBytes": row.size_bytes,
            "downloadUrl": download_url,
            "expiresInSeconds": expires,
            "createdAt": _iso(row.created_at),
        }

    def get_file(self, file_id: str) -> Dict[str, Any]:
        row = self._svc.get_by_id(file_id)
        return {"_bare": True, "_type": "FileObject", **_file_dict(row)}

    def get_download_url(
        self,
        file_id: str,
        request: Request,
        caller_user_id: Optional[str],
    ) -> Dict[str, Any]:
        row, url, expires = self._svc.get_download_url(
            file_id,
            actor_user_id=caller_user_id,
            ip_address=_ip(request),
            user_agent=_ua(request),
        )
        return {
            "_bare": True,
            "_type": "FileDownload",
            "fileId": row.id,
            "originalFilename": row.original_filename,
            "mimeType": row.mime_type,
            "sizeBytes": row.size_bytes,
            "downloadUrl": url,
            "expiresInSeconds": expires,
        }

    def search(
        self,
        *,
        folder: Optional[str],
        entity_type: Optional[str],
        entity_id: Optional[str],
        uploaded_by: Optional[str],
        include_deleted: bool,
        offset: int,
        page_size: int,
        caller_user_id: Optional[str],
        request: Request,
    ) -> Dict[str, Any]:
        rows, total = self._svc.search(
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            uploaded_by=uploaded_by,
            include_deleted=include_deleted,
            offset=offset,
            page_size=page_size,
            actor_user_id=caller_user_id,
            ip_address=_ip(request),
            user_agent=_ua(request),
        )
        elements = [_file_dict(r) for r in rows]
        return {
            "_bare": True,
            "_type": "Collection",
            "total": total,
            "count": len(elements),
            "pageSize": page_size,
            "offset": offset,
            "_embedded": {"elements": elements},
        }

    def delete(
        self,
        file_id: str,
        *,
        hard_delete: bool = False,
        caller_user_id: Optional[str],
        request: Request,
    ) -> Dict[str, Any]:
        row = self._svc.delete(
            file_id,
            actor_user_id=caller_user_id,
            hard_delete=hard_delete,
            ip_address=_ip(request),
            user_agent=_ua(request),
        )
        return {
            "_bare": True,
            "_type": "Success",
            "message": f"File {file_id} deleted.",
            "fileId": file_id,
        }

    def restore(
        self,
        file_id: str,
        *,
        caller_user_id: Optional[str],
        request: Request,
    ) -> Dict[str, Any]:
        row = self._svc.restore(
            file_id,
            actor_user_id=caller_user_id,
            ip_address=_ip(request),
            user_agent=_ua(request),
        )
        return {
            "_bare": True,
            "_type": "Success",
            "message": f"File {file_id} restored.",
            "fileId": file_id,
        }

    def search_audit_logs(
        self,
        *,
        file_id: Optional[str],
        action: Optional[str],
        actor_user_id: Optional[str],
        folder: Optional[str],
        entity_type: Optional[str],
        entity_id: Optional[str],
        offset: int,
        page_size: int,
    ) -> Dict[str, Any]:
        rows, total = self._svc.search_audit_logs(
            file_id=file_id,
            action=action,
            actor_user_id=actor_user_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            offset=offset,
            page_size=page_size,
        )
        elements = [_audit_dict(r) for r in rows]
        return {
            "_bare": True,
            "_type": "Collection",
            "total": total,
            "count": len(elements),
            "pageSize": page_size,
            "offset": offset,
            "_embedded": {"elements": elements},
        }
