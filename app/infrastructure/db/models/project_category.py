"""Project category catalog (doc 37 part 1).

Replaces the in-code ``PROJECT_CATEGORY_CHOICES`` tuple in
``app/api/v3/projects/services/transitions.py``. The tuple stays in
source as the seed list AND the in-code fallback used when the DB
catalog has no rows (e.g. fresh in-memory test DB before init_db has
run). Same idiom as ``project_status_transitions``.

Built-in seed: ``MSAP``, ``MSIP``, ``BSP``, ``others``. The ``others``
row carries ``requires_other=True`` to mirror the divisions pattern —
selecting it triggers the FE to show a free-text follow-up
(``categoryOther`` + ``categoryOtherReason`` on the project payload).
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectCategoryModel(Base):
    __tablename__ = "project_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    # True only on rows that prompt the FE to show categoryOther +
    # categoryOtherReason follow-up inputs. The seeded ``others`` row
    # uses this; user-added rows leave it false.
    requires_other = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(
        UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_project_categories_active_code", "active", "code"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectCategoryModel(code='{self.code}', "
            f"builtin={self.is_builtin}, active={self.active})>"
        )
