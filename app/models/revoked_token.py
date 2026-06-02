"""revoked_tokens — JWT blacklist (logout, force-revoke).

PK is the jti. Cheap O(1) lookup on every authed request across all services.

WARNING: READ cross-schema by all other services for their AuthMiddleware
jti checks. Mirrored in:
  - services/pmis-masters-management/app/models/_cross_schema.py
  - services/pmis-project-management/app/models/_cross_schema.py
  - services/pmis-notification-management/app/models/_cross_schema.py
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    __table_args__ = (
        Index("ix_revoked_tokens_user_id", "user_id"),
        Index("ix_revoked_tokens_expires_at", "expires_at"),
        {"schema": "users"},
    )

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    # When the token would have naturally expired — rows past this point
    # can be GC'd by a periodic cleanup (not implemented in this refactor).
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
