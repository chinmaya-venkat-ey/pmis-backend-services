"""Permission catalog (doc 21 part B).

A permission is identified by its ``code`` — a stable, human-readable
string like ``"projects:create"`` or ``"master_data:manage"``. Routes
reference permissions by code via the ``require_permission`` decorator.

``is_builtin`` flags codes that originate from the in-code permission
registry (``app/core/permissions.py``); these rows are inserted on
startup. Custom permissions added via the API have ``is_builtin=False``
and may be edited or deleted freely. Built-in rows are protected against
delete and code-rename via the management endpoints.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class PermissionModel(Base):
    __tablename__ = "permissions"

    code = Column(String(128), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PermissionModel(code='{self.code}', is_builtin={self.is_builtin})>"
