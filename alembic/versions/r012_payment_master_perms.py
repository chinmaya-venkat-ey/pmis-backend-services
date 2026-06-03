"""Seed permission rows + grants for the payment-master catalogs.

Revision ID: r012_payment_master_perms
Revises: r011_org_role_backfill
Create Date: 2026-06-03

Why:
  The Project-Finance ("payment") screen adds two masters catalogs in
  pmis-masters-management — cost_types and frequencies — each with the
  standard granular pair:

    cost_types:read / cost_types:manage
    frequencies:read / frequencies:manage

  Read codes are granted to every standard role that can already read the
  other masters (org_admin / project_admin / project_member /
  division_member) so the finance dropdowns populate. Manage codes go to
  the admin tiers only (super_admin / admin — who also pass via
  admin-bypass, but we seed the explicit rows for hygiene).

  All operations use ON CONFLICT DO NOTHING — re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r012_payment_master_perms"
down_revision: str = "r011_org_role_backfill"
branch_labels = None
depends_on = None


_READ_CODES = ("cost_types:read", "frequencies:read")
_MANAGE_CODES = ("cost_types:manage", "frequencies:manage")

# Roles that hold the other masters:read codes (mirror of r001 _ALL_MASTERS_READ
# grantees) get the new read codes too.
_READ_GRANTEES = ("org_admin", "project_admin", "project_member", "division_member")
# Manage stays with the admin tiers.
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
                    "VALUES (:rid, :code) "
                    "ON CONFLICT (role_id, permission_code) DO NOTHING"
                ),
                {"rid": role_id, "code": code},
            )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Ensure every code row exists before the FK insert.
    for code in (*_READ_CODES, *_MANAGE_CODES):
        _ensure_permission(bind, code)

    # 2. Grants.
    _grant(bind, _READ_GRANTEES, _READ_CODES)
    _grant(bind, _MANAGE_GRANTEES, (*_READ_CODES, *_MANAGE_CODES))


def downgrade() -> None:
    # Intentional no-op: removing permissions that callers rely on would
    # silently lock out the finance dropdowns.
    pass
