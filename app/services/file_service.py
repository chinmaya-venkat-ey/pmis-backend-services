"""FileService — business logic for all file operations.

Orchestrates: file validation → S3 upload → DB persist → audit log.
All S3 I/O is delegated to S3Client (app/utilities/s3_client.py).
All DB I/O is delegated to the repository layer.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import (
    FileExtensionNotAllowedError,
    FileNotFoundError,
    FileTooLargeError,
    S3DeleteError,
)
from app.models.file_audit_log import FileAuditLog
from app.models.file_object import FileObject
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.file_repository import FileRepository
from app.utilities.file_signature import detect_mime
from app.utilities.logger import get_logger
from app.utilities.s3_client import S3Client, build_s3_key, sanitize_filename


logger = get_logger(__name__)

# Actions emitted to the audit log.
ACTION_UPLOAD = "upload"
ACTION_DOWNLOAD = "download"
ACTION_DELETE = "delete"
ACTION_RESTORE = "restore"
ACTION_LIST = "list"
ACTION_SEARCH = "search"


class FileService:
    def __init__(self, db: Session, s3: S3Client):
        self.db = db
        self.s3 = s3
        self._files = FileRepository(db)
        self._audit = AuditLogRepository(db)

    # ------------------------------------------------------------------ upload

    def upload(
        self,
        upload: UploadFile,
        *,
        folder: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        extra_metadata: Optional[Dict[str, Any]],
        actor_user_id: Optional[str],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[FileObject, str, Optional[int]]:
        """Validate, upload to S3, persist metadata, write audit log.

        Returns (FileObject row, download_url, expires_in_seconds).
        """
        self._validate_extension(upload.filename or "unnamed")

        # Read content once so we can hash and check size.
        content = upload.file.read()
        size_bytes = len(content)
        self._validate_size(size_bytes, upload.filename or "")

        mime_type = detect_mime(content, upload.filename or "")
        content_hash = hashlib.sha256(content).hexdigest()

        safe_name = sanitize_filename(upload.filename or "unnamed")
        file_id = str(uuid4())
        s3_key = build_s3_key(
            prefix=settings.s3_key_prefix,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            filename=safe_name,
        )

        # Upload bytes to S3.
        public_url = self.s3.upload_bytes(
            key=s3_key,
            data=content,
            content_type=mime_type or "application/octet-stream",
            metadata={
                "file-id": file_id,
                "uploaded-by": actor_user_id or "",
                "original-filename": upload.filename or "unnamed",
            },
        )

        # Persist metadata.
        row = self._files.create(
            file_id=file_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            original_filename=upload.filename or "unnamed",
            s3_key=s3_key,
            s3_bucket=settings.s3_bucket_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
            public_url=public_url,
            extra_metadata=extra_metadata,
            uploaded_by=actor_user_id,
        )

        # Audit.
        self._audit.write(
            action=ACTION_UPLOAD,
            file_id=file_id,
            actor_user_id=actor_user_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            original_filename=upload.filename,
            extra_metadata={"size_bytes": size_bytes, "mime_type": mime_type},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        self.db.refresh(row)

        download_url, expires = self._resolve_download_url(row)
        return row, download_url, expires

    # ---------------------------------------------------------------- download

    def get_download_url(
        self,
        file_id: str,
        *,
        actor_user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[FileObject, str, Optional[int]]:
        row = self._files.get_active_by_id(file_id)
        if row is None:
            raise FileNotFoundError(f"File {file_id} not found.")

        download_url, expires = self._resolve_download_url(row)

        # Audit download (non-blocking — best-effort).
        self._audit.write(
            action=ACTION_DOWNLOAD,
            file_id=file_id,
            actor_user_id=actor_user_id,
            folder=row.folder,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            original_filename=row.original_filename,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()

        return row, download_url, expires

    def _resolve_download_url(self, row: FileObject) -> Tuple[str, Optional[int]]:
        if row.public_url:
            return row.public_url, None
        url = self.s3.presign_get(row.s3_key, expires_in=settings.s3_presigned_url_expires)
        return url, settings.s3_presigned_url_expires

    # ------------------------------------------------------------------ search

    def search(
        self,
        *,
        folder: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        include_deleted: bool = False,
        offset: int = 1,
        page_size: int = 20,
        actor_user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[List[FileObject], int]:
        rows, total = self._files.search(
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            uploaded_by=uploaded_by,
            include_deleted=include_deleted,
            offset=offset,
            page_size=page_size,
        )
        self._audit.write(
            action=ACTION_SEARCH,
            actor_user_id=actor_user_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            extra_metadata={
                "offset": offset, "page_size": page_size,
                "include_deleted": include_deleted, "result_count": len(rows),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        return rows, total

    # ---------------------------------------------------------------- get one

    def get_by_id(self, file_id: str) -> FileObject:
        row = self._files.get_active_by_id(file_id)
        if row is None:
            raise FileNotFoundError(f"File {file_id} not found.")
        return row

    # ------------------------------------------------------------------ delete

    def delete(
        self,
        file_id: str,
        *,
        actor_user_id: Optional[str] = None,
        hard_delete: bool = False,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> FileObject:
        row = self._files.get_active_by_id(file_id)
        if row is None:
            raise FileNotFoundError(f"File {file_id} not found.")

        if hard_delete:
            # Remove from S3, then delete the DB row entirely.
            try:
                self.s3.delete(row.s3_key)
            except Exception as exc:
                logger.warning("S3 delete failed for key=%s: %s", row.s3_key, exc)
            self.db.delete(row)
            self._audit.write(
                action=f"{ACTION_DELETE}:hard",
                file_id=file_id,
                actor_user_id=actor_user_id,
                folder=row.folder,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                original_filename=row.original_filename,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            return row

        # Soft delete — preserve S3 object; stamp deleted_at only.
        updated = self._files.soft_delete(file_id, deleted_by=actor_user_id)
        self._audit.write(
            action=ACTION_DELETE,
            file_id=file_id,
            actor_user_id=actor_user_id,
            folder=row.folder,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            original_filename=row.original_filename,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        return updated or row

    # ----------------------------------------------------------------- restore

    def restore(
        self,
        file_id: str,
        *,
        actor_user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> FileObject:
        row = self._files.get_by_id(file_id)
        if row is None:
            raise FileNotFoundError(f"File {file_id} not found.")
        if row.deleted_at is None:
            raise FileNotFoundError(f"File {file_id} is not deleted.")

        updated = self._files.restore(file_id)
        self._audit.write(
            action=ACTION_RESTORE,
            file_id=file_id,
            actor_user_id=actor_user_id,
            folder=row.folder,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            original_filename=row.original_filename,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        return updated or row

    # ------------------------------------------------------------ audit search

    def search_audit_logs(
        self,
        *,
        file_id: Optional[str] = None,
        action: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        folder: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        offset: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[FileAuditLog], int]:
        return self._audit.search(
            file_id=file_id,
            action=action,
            actor_user_id=actor_user_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            offset=offset,
            page_size=page_size,
        )

    # ------------------------------------------------------------ validation

    def _validate_extension(self, filename: str) -> None:
        allowed = {
            ext.strip().lower()
            for ext in settings.allowed_extensions.split(",")
            if ext.strip()
        }
        if not allowed:
            return
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in allowed:
            raise FileExtensionNotAllowedError(
                f"File extension '.{ext}' is not allowed. "
                f"Allowed: {', '.join(sorted(allowed))}."
            )

    def _validate_size(self, size: int, filename: str) -> None:
        if size > settings.max_upload_bytes:
            mb = settings.max_upload_bytes // (1024 * 1024)
            raise FileTooLargeError(
                f"File '{filename}' exceeds the {mb} MB upload limit "
                f"({size:,} bytes)."
            )
