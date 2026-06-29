"""Seed permission rows + grants for the carry_forward_methods master catalog.

Revision ID: r026_carry_forward_method_perms
Revises: r025_payment_type_perms
Create Date: 2026-06-29

Why:
  pmis-masters-management adds a new master catalog — carry_forward_methods —
  feeding the Project-Finance carry-forward "method" selector, with the
  standard granular pair:

    carry_forward_methods:read / carry_forward_methods:manage

  Mirrors r025 (payment_types). Read goes to every role that already reads the
  other masters (org_admin / project_admin / project_member / division_member)
  so the selector populates; manage goes to the admin tiers (super_admin /
  admin). Since the A1 audit removed the admin auto-bypass, the admin tiers
  must hold these codes EXPLICITLY.

  All operations use ON CONFLICT DO NOTHING — re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r026_carry_forward_method_perms"
down_revision: str = "r025_payment_type_perms"
branch_labels = None
depends_on = None


_READ_CODES = ("carry_forward_methods:read",)
_MANAGE_CODES = ("carry_forward_methods:manage",)

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
                    "VALUES (:rid, :code) "
                    "ON CONFLICT (role_id, permission_code) DO NOTHING"
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
    # Intentional no-op: removing permissions callers rely on would lock out
    # the carry-forward-method selector.
    pass
