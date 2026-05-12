"""Read-only mirror of the monolith's ``divisions`` table.

Doc 49: user-mgmt validates ``User.division`` against the divisions
master table — same column layout as the monolith's owning model. The
table itself is created by monolith's alembic migrations (both services
target the same ``pmis_db``); user-mgmt declares the mapping here only
so ORM queries are typed and so ``Base.metadata.create_all`` builds the
table inside in-memory SQLite test DBs.

Schema is intentionally minimal — only the columns user-mgmt reads.
Extra columns added on the monolith side (e.g. ``email`` /
``phone_number`` in doc 36) are present in production but not declared
here, which is fine for read-only access.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Index, Integer, String

from ..utc_datetime import UtcDateTime
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

    # Doc 36 columns (email/phone_number) exist in production but
    # aren't declared here — user-mgmt never reads or writes them.

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_divisions_code_active", "code", "active"),
    )
