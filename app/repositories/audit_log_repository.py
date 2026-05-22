"""Audit log data access layer — append-only writes and filtered reads."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.file_audit_log import FileAuditLog


class AuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def write(
        self,
        *,
        action: str,
        file_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        folder: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        original_filename: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> FileAuditLog:
        row = FileAuditLog(
            action=action,
            file_id=file_id,
            actor_user_id=actor_user_id,
            folder=folder,
            entity_type=entity_type,
            entity_id=entity_id,
            original_filename=original_filename,
            extra_metadata=extra_metadata,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        return row

    def search(
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
        stmt = select(FileAuditLog)

        if file_id is not None:
            stmt = stmt.where(FileAuditLog.file_id == file_id)
        if action is not None:
            stmt = stmt.where(FileAuditLog.action == action)
        if actor_user_id is not None:
            stmt = stmt.where(FileAuditLog.actor_user_id == actor_user_id)
        if folder is not None:
            stmt = stmt.where(FileAuditLog.folder == folder)
        if entity_type is not None:
            stmt = stmt.where(FileAuditLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(FileAuditLog.entity_id == entity_id)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = self.db.execute(total_stmt).scalar_one()

        rows = self.db.execute(
            stmt.order_by(FileAuditLog.created_at.desc())
            .offset((offset - 1) * page_size)
            .limit(page_size)
        ).scalars().all()

        return list(rows), total
