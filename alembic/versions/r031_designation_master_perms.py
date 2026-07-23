"""Seed permission rows + grants for the designations catalog.

Revision ID: r031_designation_master_perms
Revises: r030_session_admin
Create Date: 2026-07-23

Why:
  pmis-masters-management adds a new ``designations`` catalog with the standard
  granular pair (designations:read / designations:manage). Mirror the other
  masters grants (see r012_payment_master_perms):
    * read  → the standard roles that already read the other masters, so a
              designation picker populates.
    * manage → the admin tiers only.
  All operations use ON CONFLICT DO NOTHING — re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r031_designation_master_perms"
down_revision: str = "r030_session_admin"
branch_labels = None
depends_on = None


_READ_CODES = ("designations:read",)
_MANAGE_CODES = ("designations:manage",)

_READ_GRANTEES = ("org_admin", "project_admin", "project_member", "division_member")
_MANAGE_GRANTEES = ("super_admin", "admin")


def _ensure_permission(bind, code: str) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO users.permissions (code, name, description, is_builtin) "
            "VALUES (:code, :code, :code, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": code},
    )


def _grant(bind, role_names, codes) -> None:
    role_rows = bind.execute(
        sa.text("SELECT name, id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(role_names)},
    ).fetchall()
    for _name, role_id in role_rows:
        for code in codes:
            bind.execute(
                sa.text(
                    "INSERT INTO users.role_permissions (role_id, permission_code) "
                    "VALUES (:rid, :code) ON CONFLICT (role_id, permission_code) DO NOTHING"
                ),
                {"rid": role_id, "code": code},
            )


def upgrade() -> None:
    bind = op.get_bind()
    for code in (*_READ_CODES, *_MANAGE_CODES):
        _ensure_permission(bind, code)
    _grant(bind, _READ_GRANTEES, _READ_CODES)
    _grant(bind, _MANAGE_GRANTEES, (*_READ_CODES, *_MANAGE_CODES))


def downgrade() -> None:
    # No-op: removing permissions callers rely on would lock out the picker.
    pass
