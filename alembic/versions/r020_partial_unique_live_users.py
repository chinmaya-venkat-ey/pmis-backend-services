"""Free a deleted user's unique fields for reuse (Bug #138).

Revision ID: r020_partial_unique_on_active_users
Revises: r019_remove_division_other_perms
Create Date: 2026-06-08

Bug #138: when a user is DELETED its unique fields (login, email) must become
free to reuse; when a user is only DEACTIVATED they stay reserved. In this
system "delete" == soft-delete (``deleted_at`` set) and "deactivate" ==
``status='inactive'`` with ``deleted_at`` still NULL. So scope the login /
email uniqueness to live rows only — a partial unique index
``WHERE deleted_at IS NULL``:

  - soft-deleted row  -> outside the index -> login/email free for a new user
  - deactivated row   -> deleted_at IS NULL -> still inside -> stays reserved
  - restoring a user whose value was reused by a live user -> unique violation
    (the bug's "must change the unique fields first" behaviour)

``user_code`` stays globally unique (system-generated, never reused).

Safe to apply: the existing FULL unique indexes already guarantee every live
row is unique, so the narrower partial index has no existing violations.

Downgrade re-tightens to FULL unique indexes; it will fail if by then a
deleted row shares a value with a live row (the new behaviour deliberately
allows that), which is the expected cost of reverting this semantics change.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r020_partial_unique_live_users"
down_revision: str = "r019_remove_division_other_perms"
branch_labels = None
depends_on = None


_LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    op.drop_index("ix_users_login", table_name="users", schema="users")
    op.create_index(
        "ix_users_login", "users", ["login"], unique=True, schema="users",
        postgresql_where=_LIVE,
    )
    op.drop_index("ix_users_email", table_name="users", schema="users")
    op.create_index(
        "ix_users_email", "users", ["email"], unique=True, schema="users",
        postgresql_where=_LIVE,
    )


def downgrade() -> None:
    op.drop_index("ix_users_login", table_name="users", schema="users")
    op.create_index("ix_users_login", "users", ["login"], unique=True, schema="users")
    op.drop_index("ix_users_email", table_name="users", schema="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema="users")
