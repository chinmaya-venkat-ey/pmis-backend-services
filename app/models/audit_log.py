"""audit_logs — append-only trail of RBAC mutations (F16).

Every role grant / revoke / role-permission change writes one row here so
questions like "who granted admin@project to this user, and when?" are
answerable. user-svc OWNS this table; no other service reads it (no
cross-schema mirror).

Append-only by convention — the repository only INSERTs. ``before`` /
``after`` carry a small JSON snapshot of the affected row's salient fields.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
        Index("ix_audit_logs_target_user_id", "target_user_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Who performed the action (the caller). NULL only for system/migration writes.
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Dotted verb, e.g. "role_assignment.create", "role_assignment.delete".
    action: Mapped[str] = mapped_column(String(64))
    # The kind of row affected, e.g. "user_role_assignment".
    resource_type: Mapped[str] = mapped_column(String(64))
    # The affected row's id (stringified), or a scope id for bulk ops.
    resource_id: Mapped[Optional[str]] = mapped_column(String(64))
    # The user the action was performed ON (the grantee), when applicable.
    target_user_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Small JSON snapshots of the salient fields before/after the change.
    before: Mapped[Optional[dict]] = mapped_column(JSON)
    after: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
