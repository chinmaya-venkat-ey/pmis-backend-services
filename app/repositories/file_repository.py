"""File object data access layer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.file_object import FileObject


class FileRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, file_id: str) -> Optional[FileObject]:
        return self.db.get(FileObject, file_id)

    def get_active_by_id(self, file_id: str) -> Optional[FileObject]:
        return self.db.execute(
            select(FileObject)
            .where(FileObject.id == file_id)
            .where(FileObject.deleted_at.is_(None))
        ).scalar_one_or_none()

    def create(
        self,
        *,
        file_id: str,
        folder: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        original_filename: str,
        s3_key: str,
        s3_bucket: str,
        mime_type: Optional[str],
        size_bytes: Optional[int],
        content_hash: Optional[str],
        public_url: Optional[str],
        extra_metadata: Optional[dict],
        uploaded_by: Optional[str],
    ) -> FileObject:
        now = datetime.now(timezone.utc)
        row = FileObject(
            id=file_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            original_filename=original_filename,
            s3_key=s3_key,
            s3_bucket=s3_bucket,
            mime_type=mime_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
            public_url=public_url,
            extra_metadata=extra_metadata,
            uploaded_by=uploaded_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        return row

    def soft_delete(self, file_id: str, deleted_by: Optional[str]) -> Optional[FileObject]:
        row = self.get_active_by_id(file_id)
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        row.deleted_at = now
        row.deleted_by = deleted_by
        row.updated_at = now
        return row

    def restore(self, file_id: str) -> Optional[FileObject]:
        row = self.get_by_id(file_id)
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        row.deleted_at = None
        row.deleted_by = None
        row.updated_at = now
        return row

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
    ) -> Tuple[List[FileObject], int]:
        stmt = select(FileObject)

        if not include_deleted:
            stmt = stmt.where(FileObject.deleted_at.is_(None))
        if folder is not None:
            stmt = stmt.where(FileObject.folder == folder)
        if entity_type is not None:
            stmt = stmt.where(FileObject.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(FileObject.entity_id == entity_id)
        if uploaded_by is not None:
            stmt = stmt.where(FileObject.uploaded_by == uploaded_by)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self.db.execute(total_stmt).scalar_one()

        rows = self.db.execute(
            stmt.order_by(FileObject.created_at.desc())
            .offset((offset - 1) * page_size)
            .limit(page_size)
        ).scalars().all()

        return list(rows), total
