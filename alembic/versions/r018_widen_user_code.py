"""Widen users.users.user_code from varchar(16) to varchar(24).

Revision ID: r018_widen_user_code
Revises: r017_user_full_name
Create Date: 2026-06-05

Bug: the original create-users migration (u1a000000001) made ``user_code``
``VARCHAR(16)``, but the model declares ``String(24)`` and
``generate_user_code`` emits ``US-<slug:4>-<YYMMDDHHMMSS+ms>`` (~20-23 chars).
On a database built from the migrations the column is 16, so EVERY user
create fails with ``StringDataRightTruncation``. This aligns the column with
the model + the generator.

Widening only — never truncates existing values. Idempotent.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r018_widen_user_code"
down_revision: str = "r017_user_full_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users", "user_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
        existing_nullable=True,
        schema="users",
    )


def downgrade() -> None:
    # Intentional no-op. Narrowing user_code back to VARCHAR(16) would fail
    # with StringDataRightTruncation on any DB that has created users since
    # this ran (generate_user_code emits ~20-23 chars) — i.e. it would
    # re-introduce the exact bug this migration fixes. Leaving the column at
    # VARCHAR(24) is harmless on rollback (it is simply wider than the
    # reverted model declares), so a wholesale downgrade past r018 is safe.
    pass
