"""password_reset_tokens — single-use HMAC-hashed reset tokens.

Token cleartext is sent to the user via email/SMS; the DB stores only the
hash. Single-use enforced by setting `consumed_at` on first verify.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_prt_token_hash", "token_hash", unique=True),
        Index("ix_prt_user_consumed", "user_id", "consumed_at"),
        Index("ix_prt_expires_at", "expires_at"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.users.id"),
    )
    channel: Mapped[str] = mapped_column(String(16))   # "email" or "sms"
    token_hash: Mapped[str] = mapped_column(String(255))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
