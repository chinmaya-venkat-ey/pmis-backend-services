"""RefreshToken — one row per ISSUED refresh token (multi-session support).

Replaces the single ``users.refresh_token_jti`` column, which held only ONE
active refresh token per user. With a single slot, a 2nd login/device/tab
silently invalidated the others, and two near-simultaneous refreshes evicted
each other from the one grace slot — the long-standing "logged out for no
reason, every now and then" bug.

Now every issued refresh token is its own row, so concurrent sessions coexist.
Rotation never *evicts*: it stamps ``rotated_at`` on the old row (which stays
valid for a short grace window so in-flight refreshes don't fail) and inserts
a fresh row.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_jti", "jti", unique=True),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
        {"schema": "users"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # The refresh token's jti (uuid4().hex). Unique among all issued tokens.
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The JWT carries the authoritative exp; this is for pruning + a belt-and-
    # braces server-side expiry check.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when this token is rotated; it stays valid for the grace window after.
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Set on logout / deactivation / password-reset — hard-kills the token.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
