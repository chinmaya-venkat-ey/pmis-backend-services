"""User database model — owned by pmis-user-service.

Column-for-column identical to the monolith's ``UserModel`` so the shared
Postgres table can be written by user-service and read by backend without
either having a stale mapping.

Soft-delete columns (`deleted_at`, `deleted_by`) ride alongside the
status field — DELETE /users/{id} sets them and flips status='inactive'
without dropping mapping rows.

`vendor_id` is the FK to the user's associated vendor (single vendor
per user, per product spec). `division` is one of DIVISION_CHOICES
('tmd1', 'tmd2', 'others'); when 'others', a free-text label is required
and stored in `division_other`.

Refresh-token rotation uses a two-slot scheme:
  - ``refresh_token_jti`` / ``refresh_token_expires_at``  : the live jti
  - ``previous_refresh_token_jti`` / ``..._valid_until``  : the rotated-out
    jti held for ``REFRESH_TOKEN_GRACE_SECONDS`` to absorb concurrent
    refreshes / multi-tab races.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    login = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    admin = Column(Boolean, default=False, nullable=False)
    status = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Refresh token tracking — single-active-refresh-token slot.
    refresh_token_jti = Column(String(64), nullable=True)
    refresh_token_expires_at = Column(DateTime, nullable=True)

    # Grace window: the just-rotated-out jti is held here for
    # REFRESH_TOKEN_GRACE_SECONDS (see settings) so concurrent /refresh
    # races, multi-tab login, and stale-token retry queues don't get
    # locked out by the atomic-swap losing path. NULL once expired or
    # cleared on explicit logout.
    previous_refresh_token_jti = Column(String(64), nullable=True)
    previous_refresh_token_jti_valid_until = Column(DateTime, nullable=True)

    # Vendor association (single vendor per user). Nullable so the
    # bootstrap admin (created by init_db) and any pre-feature legacy
    # rows remain valid; the API enforces it as required at create time.
    #
    # ``use_alter=True`` breaks the table-creation cycle between users
    # and vendors (vendors.deleted_by → users.id closes the loop).
    # Without it SQLAlchemy can't sort the tables for create_all/drop_all
    # and emits a SAWarning during test teardown. The named constraint
    # lets the ALTER-ADD-FOREIGN-KEY pass after both tables exist.
    vendor_id = Column(
        String(36),
        ForeignKey(
            "vendors.id",
            name="fk_users_vendor_id",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )

    # Division: one of DIVISION_CHOICES ('tmd1', 'tmd2', 'others').
    # Same nullable-DB / required-API pattern as vendor_id.
    division = Column(String(32), nullable=True)
    # Free-text label when division == 'others'; NULL otherwise.
    division_other = Column(String(255), nullable=True)

    # Soft-delete. A non-NULL deleted_at hides the user from list/get
    # endpoints by default. Project_members mappings stay intact so
    # restore (PATCH status=active OR POST /restore) preserves history.
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("idx_users_login", "login"),
        Index("idx_users_email", "email"),
        Index("idx_users_status", "status"),
        Index("idx_users_created_at", "created_at"),
        Index("idx_users_deleted_at", "deleted_at"),
        Index("idx_users_vendor_id", "vendor_id"),
    )

    def __repr__(self) -> str:
        return f"<UserModel(id={self.id}, login='{self.login}', email='{self.email}')>"
