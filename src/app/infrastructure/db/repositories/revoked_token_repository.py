"""Repository for the access-token revocation blacklist."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models.revoked_token import RevokedTokenModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RevokedTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        """True iff ``jti`` is in the blacklist AND the token's natural
        expiry is still in the future. Past-expiry rows are ignored — the
        JWT verifier rejects expired tokens already.
        """
        if not jti:
            return False
        row = (
            self.db.query(RevokedTokenModel.jti)
            .filter(
                and_(
                    RevokedTokenModel.jti == jti,
                    RevokedTokenModel.expires_at > _utcnow(),
                )
            )
            .first()
        )
        return row is not None

    def revoke(
        self, *, jti: str, expires_at: datetime, user_id: Optional[int] = None,
    ) -> None:
        """Insert a revocation row. Idempotent: re-revoking the same jti is
        a silent no-op (PK conflict swallowed). Caller commits.
        """
        if not jti:
            return
        existing = (
            self.db.query(RevokedTokenModel.jti)
            .filter(RevokedTokenModel.jti == jti)
            .first()
        )
        if existing is not None:
            return  # already revoked; idempotent
        self.db.add(
            RevokedTokenModel(
                jti=jti,
                user_id=user_id,
                expires_at=expires_at,
            )
        )
        self.db.flush()

    def cleanup_expired(self) -> int:
        """Delete rows whose ``expires_at`` is in the past. Optional;
        purely a disk-space optimization. Returns the count deleted.

        Not wired into a cron right now — call manually or from a future
        scheduled task.
        """
        deleted = (
            self.db.query(RevokedTokenModel)
            .filter(RevokedTokenModel.expires_at <= _utcnow())
            .delete(synchronize_session=False)
        )
        self.db.flush()
        return deleted
