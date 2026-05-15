"""Project status transition catalog — owned by pmis-masters-management.

A row per legal (from_status, to_status) edge in the project lifecycle.
project-svc reads this catalog to validate status transitions on
PATCH /project/projects/{uuid}/update.

`from_status=NULL` represents the initial-status seed (status the system
accepts on a fresh create).

Unique constraint on (from_status, to_status) — no contradictory rules
for the same edge.

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\infrastructure\\db\\models\\project_status_transition.py:43.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectStatusTransition(Base):
    __tablename__ = "project_status_transitions"
    __table_args__ = (
        UniqueConstraint(
            "from_status", "to_status",
            name="uq_project_status_transitions_edge",
        ),
        Index("ix_pst_from_status", "from_status"),
        Index("ix_pst_to_status", "to_status"),
        Index("ix_pst_active", "active"),
        Index("idx_pst_to_status_active", "to_status", "active"),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NULL = initial-status seed.
    from_status: Mapped[Optional[str]] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50))
    # Round-7: FSM gates by PERMISSION CODE. NULL = no special perm required.
    permission_code: Mapped[Optional[str]] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
