"""User database model.

Soft-delete columns (`deleted_at`, `deleted_by`) were added so DELETE
/users/{id} hides the user without losing project_members mappings or
audit history.

`vendor_id` is the FK to the user's associated vendor (single vendor
per user, per product spec). `division` is one of DIVISION_CHOICES
('tmd1', 'tmd2', 'others'); when 'others', a free-text label is
required and stored in `division_other`.
"""
from datetime import datetime, timezone
from uuid import uuid4


def _utcnow():
    return datetime.now(timezone.utc)
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from ..utc_datetime import UtcDateTime
from ..session import Base


class UserModel(Base):
    """User database model."""

    __tablename__ = "users"

    # Doc 26: ``id`` is now a UUID (String(36)) — replaces the legacy
    # auto-incrementing integer. Aligns with every other resource
    # (projects, vendors, milestones, tasks, …) so ID handling is
    # uniform across the API surface. The ``user_code`` column (doc 25)
    # is still the human-readable display identifier; ``id`` is the
    # canonical machine identifier and FK target.
    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid4()),
    )
    # Doc 25: human-readable display identifier (US-XXXX-YYMMDDHHMMSS).
    # Snapshot of ``login`` + ``created_at`` taken at create time;
    # immutable on rename. UI / search / cross-entity references show
    # the code; ``id`` is what FKs / joins use under the hood.
    user_code = Column(String(50), nullable=True, unique=True, index=True)
    login = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    # ``admin`` boolean was removed in doc 21 part B. Superuser status is
    # now derived from membership in the seeded ``admin`` role
    # (user_roles → roles). The column is dropped by alembic; on SQLite the
    # column may linger in the file but is no longer referenced anywhere.
    status = Column(String(50), default="active", nullable=False)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False, index=True)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    # Refresh token tracking for stateless rotation
    refresh_token_jti = Column(String(64), nullable=True, index=False)
    refresh_token_expires_at = Column(UtcDateTime, nullable=True)
    # Grace window: the just-rotated-out jti is held here for
    # REFRESH_TOKEN_GRACE_SECONDS (see settings) so concurrent /refresh
    # races, multi-tab login, and stale-token retry queues don't get
    # locked out by the atomic-swap losing path. NULL once expired or
    # cleared on explicit logout.
    previous_refresh_token_jti = Column(String(64), nullable=True)
    previous_refresh_token_jti_valid_until = Column(UtcDateTime, nullable=True)

    # Vendor association (single vendor per user). Nullable so the
    # bootstrap admin (created by init_db) and any pre-feature legacy
    # rows remain valid; the API enforces it as required at create time.
    #
    # ``use_alter=True`` breaks the table-creation cycle between users and
    # vendors (vendors.deleted_by → users.id closes the loop). Without it
    # SQLAlchemy can't sort the tables for create_all/drop_all and emits
    # a SAWarning during test teardown. The named constraint lets the
    # ALTER-ADD-FOREIGN-KEY pass after both tables exist.
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

    # Phone number (free-form, free-text — no regex format check; matches
    # vendor's ``phone_number`` exactly). Nullable in the DB so the
    # bootstrap admin (init_db) and any pre-feature legacy rows stay
    # valid; the wire schema enforces it as REQUIRED on create. Edits
    # leave the existing value alone unless the caller sends one.
    phone_number = Column(String(50), nullable=True)

    # Doc 45 round 9b (read-side mirror): canonical write happens in
    # user-service; project-service just needs the ORM attribute to
    # read it (the column already exists in the shared DB). Used by
    # GET /projects/{id}/assignable-users to project ``orgRole`` when
    # the user holds no scoped role assignment.
    org_role = Column(String(50), nullable=True)

    # Doc 33 change 3: per-user 2FA opt-in. Default True (mandatory by
    # default per Q3a.4); admins can flip individual users to False via
    # PATCH /users/{id} when ``REQUIRE_2FA=true`` globally would be too
    # strict for a particular account (e.g. service accounts, ops
    # users on shared keys). When the global setting is False, the
    # column is ignored — no user gets prompted for OTP.
    two_factor_enabled = Column(Boolean, default=True, nullable=False)

    # Soft-delete. A non-NULL deleted_at hides the user from list/get
    # endpoints by default. Project_members mappings stay intact so
    # restore (PATCH status=active) preserves history.
    deleted_at = Column(UtcDateTime, nullable=True, index=True)
    # Doc 26: UUID FK to users.id (was Integer pre-doc-26).
    deleted_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Indexes
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
