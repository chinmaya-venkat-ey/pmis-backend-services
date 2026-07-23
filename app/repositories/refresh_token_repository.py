"""RefreshTokenRepository — per-session refresh-token store (multi-session).

A refresh token is VALID when its row is: not revoked, not expired, and either
not yet rotated OR still inside the post-rotation grace window.

Two properties this gives us (the durable fix for the long-standing
"logged out for no reason" bug):
  - ``create`` adds a NEW row per login — a 2nd login/device/tab never clobbers
    other sessions.
  - ``rotate`` never *evicts*: it stamps ``rotated_at`` (keeping the old token
    valid for the grace window) and inserts a fresh row, so two concurrent
    refreshes of the same token both succeed instead of evicting each other.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self, *, user_id: str, jti: str, expires_at: datetime,
        access_jti: Optional[str] = None,
    ) -> RefreshToken:
        row = RefreshToken(
            id=str(uuid4()),
            user_id=user_id,
            jti=jti,
            issued_at=_utcnow(),
            expires_at=expires_at,
            access_jti=access_jti,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_active_by_jti(self, jti: str, *, grace_seconds: int) -> Optional[RefreshToken]:
        """Return the row for ``jti`` iff it is still usable: not revoked, not
        expired, and (not rotated, OR rotated but still within the grace
        window). Returns None otherwise."""
        if not jti:
            return None
        row = self.db.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        ).scalar_one_or_none()
        if row is None:
            return None
        now = _utcnow()
        if row.revoked_at is not None:
            return None
        if row.expires_at <= now:
            return None
        if row.rotated_at is not None and (
            row.rotated_at + timedelta(seconds=grace_seconds) <= now
        ):
            return None
        return row

    def rotate(
        self, old_row: RefreshToken, *, new_jti: str, new_expires_at: datetime,
        new_access_jti: Optional[str] = None,
    ) -> RefreshToken:
        """Stamp the old token as rotated (it stays valid for the grace window)
        and mint a fresh row. Never evicts, so concurrent refreshes coexist."""
        now = _utcnow()
        if old_row.rotated_at is None:
            old_row.rotated_at = now
        old_row.last_used_at = now
        return self.create(
            user_id=old_row.user_id, jti=new_jti, expires_at=new_expires_at,
            access_jti=new_access_jti,
        )

    def list_active_sessions(self, user_id: str) -> list:
        """#365: a user's live sessions (un-rotated HEAD rows — one per active
        login/device), newest first. Used by the admin session-list endpoint."""
        now = _utcnow()
        return list(self.db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > now)
            .where(RefreshToken.rotated_at.is_(None))
            .order_by(RefreshToken.issued_at.desc())
        ).scalars().all())

    def live_access_jtis(self, user_id: str) -> list:
        """#365: access jtis of every still-usable session row (heads AND
        in-grace rotated rows) for a user — everything to denylist on a hard
        revoke. Excludes already-revoked / expired rows."""
        now = _utcnow()
        rows = self.db.execute(
            select(RefreshToken.access_jti)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > now)
        ).scalars().all()
        return [j for j in rows if j]

    def get_by_jti(self, jti: str) -> Optional[RefreshToken]:
        """Raw lookup by jti (no validity filtering) — the admin revoke path
        needs the row's access_jti + owner even for an in-grace token."""
        if not jti:
            return None
        return self.db.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        ).scalar_one_or_none()

    def revoke_all_for_user(self, user_id: str) -> int:
        """Hard-kill every live session for a user (logout / deactivate /
        password-reset / delete). Returns the number revoked."""
        result = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_utcnow())
        )
        self.db.flush()
        return result.rowcount or 0

    def revoke_by_jti(self, jti: str) -> int:
        """Revoke a single token by its jti (per-session logout)."""
        if not jti:
            return 0
        result = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.jti == jti)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_utcnow())
        )
        self.db.flush()
        return result.rowcount or 0

    def delete_stale_for_user(self, user_id: str, *, grace_seconds: int) -> int:
        """Remove a user's rows that can no longer be used — expired, OR rotated
        past the grace window. Called on the hot paths (login/refresh) so the
        table stays bounded: every refresh mints a row, so without this it would
        grow without limit (a storage/DoS vector). Indexed by user_id, cheap."""
        now = _utcnow()
        grace_cutoff = now - timedelta(seconds=grace_seconds)
        result = self.db.execute(
            delete(RefreshToken).where(
                RefreshToken.user_id == user_id,
                or_(
                    RefreshToken.expires_at <= now,
                    and_(
                        RefreshToken.rotated_at.is_not(None),
                        RefreshToken.rotated_at <= grace_cutoff,
                    ),
                ),
            )
        )
        self.db.flush()
        return result.rowcount or 0

    def enforce_session_cap(self, user_id: str, *, max_active: int) -> int:
        """Defense-in-depth against login spam: keep only the newest
        ``max_active`` live sessions (un-rotated head tokens) per user; revoke
        the rest. Bounds how many concurrent sessions a single account can
        hold open at once."""
        now = _utcnow()
        heads = self.db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > now)
            .where(RefreshToken.rotated_at.is_(None))
            .order_by(RefreshToken.issued_at.desc())
        ).scalars().all()
        revoked = 0
        for row in heads[max_active:]:
            row.revoked_at = now
            revoked += 1
        self.db.flush()
        return revoked

    def prune_expired(self) -> int:
        """Global cleanup of rows past their expiry (for a periodic job)."""
        result = self.db.execute(
            delete(RefreshToken).where(RefreshToken.expires_at <= _utcnow())
        )
        self.db.flush()
        return result.rowcount or 0
