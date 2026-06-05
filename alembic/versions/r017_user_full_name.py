"""Add users.users.full_name as the single canonical name field.

Revision ID: r017_user_full_name
Revises: r016_admin_override
Create Date: 2026-06-05

The app uses `full_name` everywhere; the old first_name/last_name split was a
source of bugs (most notably: a `fullName` sent on user-create was silently
dropped, so the user list fell back to showing the login). This makes
`full_name` a real stored column and the only name the API reads/writes.

  1. Add ``users.users.full_name`` (nullable).
  2. Backfill it from the existing first_name + last_name (NULL when both are
     empty — deliberately NOT the login, which was the bug).
  3. Seed the ``users:update:full_name`` field-level permission and grant it to
     admin + super_admin (replacing users:update:first_name / :last_name as the
     gated name field).

The legacy ``first_name`` / ``last_name`` columns are intentionally LEFT in
place (no longer written) so cross-schema mirrors in other services don't
break; they can be dropped in a later coordinated migration.

Re-runnable. Per A19 a real downgrade is implemented (drop column + grants +
permission row).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r017_user_full_name"
down_revision: str = "r016_admin_override"
branch_labels = None
depends_on = None


_NEW_CODE = "users:update:full_name"
_GRANTEES = ("admin", "super_admin")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("full_name", sa.String(length=510), nullable=True),
        schema="users",
    )
    bind = op.get_bind()
    # Backfill from first/last; empty -> NULL (never the login).
    bind.execute(sa.text(
        "UPDATE users.users "
        "SET full_name = NULLIF(BTRIM(CONCAT_WS(' ', first_name, last_name)), '')"
    ))

    bind.execute(sa.text(
        "INSERT INTO users.permissions (code, name, description, is_builtin) "
        "VALUES (:c, :c, :c, true) ON CONFLICT (code) DO NOTHING"
    ), {"c": _NEW_CODE})
    for (role_id,) in bind.execute(
        sa.text("SELECT id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_GRANTEES)},
    ).fetchall():
        bind.execute(sa.text(
            "INSERT INTO users.role_permissions (role_id, permission_code) "
            "VALUES (:rid, :c) ON CONFLICT (role_id, permission_code) DO NOTHING"
        ), {"rid": role_id, "c": _NEW_CODE})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM users.role_permissions WHERE permission_code = :c"), {"c": _NEW_CODE})
    bind.execute(sa.text("DELETE FROM users.permissions WHERE code = :c"), {"c": _NEW_CODE})
    op.drop_column("users", "full_name", schema="users")
