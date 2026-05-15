"""OtpCodeRepository — OTP send/verify storage (per Q13).

Storage moved here from notification-svc's in-memory dict. notification-svc
DISPATCHES the code via SMS/email; user-svc generates + stores (hashed) +
verifies it.

Lookup by ephemeral_token_hash (FE never sees user_id during the 2FA flow).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.otp_code import OtpCode


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OtpCodeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        channel: str,
        code_hash: Optional[str],
        ephemeral_token_hash: str,
        ttl_seconds: Optional[int] = None,
    ) -> OtpCode:
        now = _utcnow()
        ttl = ttl_seconds if ttl_seconds is not None else settings.otp_ttl_seconds
        row = OtpCode(
            user_id=user_id,
            channel=channel,
            code_hash=code_hash,
            ephemeral_token_hash=ephemeral_token_hash,
            generated_at=now,
            expires_at=now + timedelta(seconds=ttl),
            attempt_count=0,
            last_sent_at=now,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_active_by_ephemeral_token(
        self, ephemeral_token_hash: str,
    ) -> Optional[OtpCode]:
        """Find a non-consumed, non-expired OTP row."""
        now = _utcnow()
        stmt = (
            select(OtpCode)
            .where(OtpCode.ephemeral_token_hash == ephemeral_token_hash)
            .where(OtpCode.consumed_at.is_(None))
            .where(OtpCode.expires_at >= now)
            .order_by(OtpCode.id.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def set_code(
        self,
        row: OtpCode,
        *,
        code_hash: str,
    ) -> OtpCode:
        """Update an existing OTP row with a freshly-generated code (resend)."""
        row.code_hash = code_hash
        row.last_sent_at = _utcnow()
        row.expires_at = _utcnow() + timedelta(seconds=settings.otp_ttl_seconds)
        row.attempt_count = 0
        self.db.flush()
        return row

    def increment_attempts(self, row: OtpCode) -> OtpCode:
        row.attempt_count = (row.attempt_count or 0) + 1
        self.db.flush()
        return row

    def consume(self, row: OtpCode) -> OtpCode:
        row.consumed_at = _utcnow()
        self.db.flush()
        return row
