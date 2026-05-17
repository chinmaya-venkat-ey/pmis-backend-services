"""otp_codes — 2FA login OTPs + post-Q13 the dispatch trail.

Per Q13: OTP storage moved here from notification-svc's in-memory dict.
notification-svc DISPATCHES the OTP code via SMS/email; this service
GENERATES, STORES (hashed), and VERIFIES it.

Lookup at verify time: by `ephemeral_token_hash` (FE never sees user_id
during the OTP flow). Attempt counter caps abuse.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OtpCode(Base):
    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("ix_otp_ephemeral_token_hash", "ephemeral_token_hash"),
        Index("ix_otp_user_consumed", "user_id", "consumed_at"),
        Index("ix_otp_expires_at", "expires_at"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.users.id"),
    )
    channel: Mapped[str] = mapped_column(String(16))   # "email" or "sms"
    code_hash: Mapped[Optional[str]] = mapped_column(String(255))
    ephemeral_token_hash: Mapped[str] = mapped_column(String(255))

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
