"""Per-session refresh tokens — multi-session support (fixes refresh eviction).

Creates ``users.refresh_tokens`` (one row per issued refresh token) so multiple
concurrent sessions (tabs / devices / re-login) coexist.

Previously a single ``users.refresh_token_jti`` column held ONE active token per
user, so a 2nd login/device silently invalidated the others, and two
near-simultaneous refreshes evicted each other from the one grace slot —
surfacing as intermittent "logged out for no reason".

Backfills each live user's current ``refresh_token_jti`` so existing sessions
survive the deploy (no mass logout). The legacy columns
(``refresh_token_jti`` / ``previous_refresh_token_jti`` /
``previous_refresh_token_jti_valid_until``) are LEFT in place (now unused) for
safe rollback; a later migration may drop them.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "r022_refresh_tokens_table"
down_revision = "r021_user_login_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema="users",
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema="users",
    )
    op.create_index(
        "ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True, schema="users",
    )
    op.create_index(
        "ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"], schema="users",
    )

    # Backfill current sessions so users aren't all logged out on deploy.
    # The refresh-token JWT carries the authoritative exp; expires_at here is
    # only for pruning/belt-and-braces, so a 7-day horizon is safe. id is a
    # 32-char md5 hex (fits String(36)); avoids any uuid-extension dependency.
    op.execute(
        """
        INSERT INTO users.refresh_tokens (id, user_id, jti, issued_at, expires_at)
        SELECT md5(u.id || u.refresh_token_jti || clock_timestamp()::text),
               u.id, u.refresh_token_jti, now(), now() + interval '7 days'
        FROM users.users u
        WHERE u.refresh_token_jti IS NOT NULL
          AND u.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens", schema="users")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens", schema="users")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens", schema="users")
    op.drop_table("refresh_tokens", schema="users")
