"""Activity status catalog (doc 37 part 1).

Replaces the in-code ``ACTIVITY_STATUS_CHOICES`` tuple in
``app/domain/activities/activity.py``. The tuple stays in source as
the seed list AND the in-code fallback used when the DB catalog has
no rows.

Built-in seed: ``not_completed`` (default), ``completed`` (terminal).

``is_terminal``: same role as in ``milestone_statuses`` — marks the
rows that the dependency-completion gate keys on (an activity with a
terminal status counts as done for upstream dependents).
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityStatusModel(Base):
    __tablename__ = "activity_statuses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    is_terminal = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_activity_statuses_active_code", "active", "code"),
    )

    def __repr__(self) -> str:
        return (
            f"<ActivityStatusModel(code='{self.code}', "
            f"terminal={self.is_terminal}, active={self.active})>"
        )
