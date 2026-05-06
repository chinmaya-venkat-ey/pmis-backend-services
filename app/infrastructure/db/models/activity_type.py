"""Activity type catalog (doc 37 part 1).

Replaces the in-code ``ACTIVITY_TYPES`` tuple in
``app/domain/activities/activity.py``. The tuple stays in source as
the seed list AND the in-code fallback used when the DB catalog has
no rows.

Built-in seed: ``standard``, ``resource``, ``transactional``. These
map to the activity type CHECK constraint values; renaming a code
would break existing rows pointing at the old value via the
``activities.type`` column. Renames go through soft-deactivate +
create-new instead.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class ActivityTypeModel(Base):
    __tablename__ = "activity_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_activity_types_active_code", "active", "code"),
    )

    def __repr__(self) -> str:
        return (
            f"<ActivityTypeModel(code='{self.code}', "
            f"builtin={self.is_builtin}, active={self.active})>"
        )
