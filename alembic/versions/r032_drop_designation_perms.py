"""Remove the designations catalog permissions (catalog dropped in masters m17).

Revision ID: r032_drop_designation_master_perms
Revises: r031_designation_master_perms
Create Date: 2026-07-30

Why:
  The masters designations catalog is removed (superseded by the leave-management
  designation-rate service). Its granular permission pair
  (designations:read / designations:manage) and all its grants are now dead, so
  drop them. Reverses r031. Idempotent (targets specific codes).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "r032_drop_designation_perms"
down_revision: str = "r031_designation_master_perms"
branch_labels = None
depends_on = None

_CODES = ("designations:read", "designations:manage")
_READ_GRANTEES = ("org_admin", "project_admin", "project_member", "division_member")
_MANAGE_GRANTEES = ("super_admin", "admin")


def upgrade() -> None:
    bind = op.get_bind()
    # Grants first (role_permissions references the permission code), then the rows.
    bind.execute(
        sa.text("DELETE FROM users.role_permissions WHERE permission_code = ANY(:codes)"),
        {"codes": list(_CODES)},
    )
    bind.execute(
        sa.text("DELETE FROM users.permissions WHERE code = ANY(:codes)"),
        {"codes": list(_CODES)},
    )


def _grant(bind, role_names, codes) -> None:
    role_rows = bind.execute(
        sa.text("SELECT id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(role_names)},
    ).fetchall()
    for (role_id,) in role_rows:
        for code in codes:
            bind.execute(
                sa.text(
                    "INSERT INTO users.role_permissions (role_id, permission_code) "
                    "VALUES (:rid, :code) ON CONFLICT (role_id, permission_code) DO NOTHING"
                ),
                {"rid": role_id, "code": code},
            )


def downgrade() -> None:
    # Restore r031: re-add the permission rows + grants.
    bind = op.get_bind()
    for code in _CODES:
        bind.execute(
            sa.text(
                "INSERT INTO users.permissions (code, name, description, is_builtin) "
                "VALUES (:code, :code, :code, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code},
        )
    _grant(bind, _READ_GRANTEES, ("designations:read",))
    _grant(bind, _MANAGE_GRANTEES, _CODES)
