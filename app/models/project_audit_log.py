"""project_audit_logs — append-only audit trail for project / milestone /
activity / task / subtask mutations.

JSON `changes` column carries the delta (before/after); `action` is one of
'create' | 'update' | 'delete' | 'restore' | 'publish' | 'close' | 'transition'.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectAuditLog(Base):
    __tablename__ = "project_audit_logs"
    __table_args__ = (
        Index("ix_pal_project_id", "project_id"),
        Index("ix_pal_target", "target_kind", "target_id"),
        Index("ix_pal_actor_user_id", "actor_user_id"),
        Index("ix_pal_created_at", "created_at"),
        {"schema": "project"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"),
    )
    target_kind: Mapped[str] = mapped_column(String(20))   # project|milestone|activity|task|subtask|comment
    target_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(32))        # create|update|delete|restore|publish|close|transition
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36))  # logical FK
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
