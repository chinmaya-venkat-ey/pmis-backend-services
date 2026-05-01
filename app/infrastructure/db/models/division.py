"""Division SQLAlchemy model.

Backs the project-owner picker (formerly the activity-resource division
picker too — same widget, same vocabulary). Three rows are seeded by
``init_db`` on first boot: ``tmd1`` / ``tmd2`` / ``others``. Additional
rows appear when a user creates a project with
``owner='others'`` and supplies a free-text ``ownerOther`` label — the
service slugifies the label to a wire code and inserts a row here so the
next project-owner dropdown carries the new option.

Schema:
- ``code``         : lowercase wire value sent in `owner` fields. Unique.
- ``label``        : display string (e.g. ``TMD1``, ``Engineering``).
- ``is_builtin``   : True for the seeded ``tmd1`` / ``tmd2`` / ``others`` rows.
                     User-added entries are False.
- ``requires_other``: True only for the ``others`` row — tells the FE to
                     show the free-text "Specify owner" follow-up input.
- ``active``       : flips a row off without deleting it (history-safe).
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class DivisionModel(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    requires_other = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_divisions_code_active", "code", "active"),
    )

    def __repr__(self) -> str:
        return (
            f"<DivisionModel(id={self.id}, code='{self.code}', "
            f"label='{self.label}', builtin={self.is_builtin}, "
            f"active={self.active})>"
        )
