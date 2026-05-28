"""Backfill super_admin + admin role_permissions

Revision ID: r002_backfill_admin_superadmin_perms
Revises: r001_reseed_role_permissions
Create Date: 2026-05-25

Why:
  The r001 reseed migration introduced new permission codes and granted
  them to org_admin / project_admin / project_member / division_member —
  but never touched super_admin (role_id=1) or admin (role_id=2). Result:
  super_admin held 137 of 153 catalog codes, admin held 135, while
  org_admin / project_admin held more. The runtime ``_is_admin`` bypass
  in core/rbac.py protects these tiers from 403s today, but the DB rows
  are inconsistent and would bite if the bypass is ever removed (security
  hardening, audit review, new role inheriting from admin's grants, etc).

  This migration is idempotent (``ON CONFLICT DO NOTHING``) and uses
  ``INSERT … SELECT FROM users.permissions`` so it auto-picks up every
  catalog code present at migration time. Future perm additions need
  either this migration to be re-run OR equivalent backfill logic in the
  migration that introduces the new code.

  super_admin → every code in users.permissions
  admin       → every code except ``users:grant_superadmin`` (which is
                spec-reserved for super_admin only)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r002_backfill_admin_perms"
down_revision: str = "r001_reseed_role_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles WHERE name IN ('super_admin', 'admin')"
    )).fetchall()
    role_id_by_name = {n: i for n, i in role_rows}

    sa_id = role_id_by_name.get("super_admin")
    admin_id = role_id_by_name.get("admin")

    # super_admin: every catalog code.
    if sa_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": sa_id})

    # admin: every catalog code EXCEPT users:grant_superadmin.
    if admin_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            WHERE code <> 'users:grant_superadmin'
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": admin_id})


def downgrade() -> None:
    # Intentional no-op: removing permissions from super_admin / admin
    # would functionally lock those roles out of new endpoints.
    pass
