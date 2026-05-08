"""Priorities catalog (doc 41).

Mirrors the activity_status / milestone_status catalogs. Holds the
set of priority codes (``p1``, ``p2``, ``p3``, …) referenced by the
``activities.priority`` column. Built-in seed rows can't be deleted.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class PriorityModel(Base):
    __tablename__ = "priorities"

    id = Column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    code = Column(String(16), nullable=False, unique=True, index=True)
    name = Column(String(64), nullable=False)
    description = Column(String(500), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, default=True, nullable=False, index=True)
    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False,
    )
    deleted_at = Column(UtcDateTime, nullable=True)

    __table_args__ = (
        Index("idx_priorities_active_code", "active", "code"),
    )

    def __repr__(self) -> str:
        return (
            f"<PriorityModel(code='{self.code}', name='{self.name}', "
            f"builtin={self.is_builtin}, active={self.active})>"
        )
