"""Add login-audit timestamps to users.users (Last Login on the profile).

Revision ID: r021_user_login_timestamps
Revises: r020_partial_unique_live_users
Create Date: 2026-06-09

Adds two nullable timestamptz columns:
  - last_login_at      : the user's most-recent login (stamped on every login)
  - previous_login_at  : the login BEFORE the most-recent one — this is the
                         "Last Login" the profile UI displays (the prior session,
                         not the current one).

Both are stamped in AuthService._issue_login (the single chokepoint that both
password login and 2FA/OTP funnel through). Nullable, no backfill — existing
users read NULL until their next two logins populate them. Non-breaking.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r021_user_login_timestamps"
down_revision: str = "r020_partial_unique_live_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="users",
    )
    op.add_column(
        "users",
        sa.Column("previous_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="users",
    )


def downgrade() -> None:
    op.drop_column("users", "previous_login_at", schema="users")
    op.drop_column("users", "last_login_at", schema="users")
