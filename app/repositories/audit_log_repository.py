"""AuditLogRepository — append-only writes to users.audit_logs (F16).

Insert-only by design. Callers pass the actor + a small before/after JSON
snapshot; the row is flushed within the caller's transaction so the audit
record commits atomically with the change it describes (or rolls back with
it).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        actor_user_id: Optional[str],
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
    ) -> AuditLog:
        row = AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            target_user_id=target_user_id,
            before=before,
            after=after,
        )
        self.db.add(row)
        self.db.flush()
        return row
