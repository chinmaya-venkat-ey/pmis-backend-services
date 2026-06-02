"""Grant every catalog code to admin and super_admin (A1 part 2 + A7 reserved-grant).

Revision ID: r005_admin_explicit_grants
Revises: r004_finance_field_perm
Create Date: 2026-06-02

Why:
  After the `_is_admin` short-circuit removal lands (Phase 4 of the
  2026-06-02 permissions audit; see permissions_implementation_plan.md
  at PMIS root), admin and super_admin must explicitly hold every
  permission code in users.permissions — they no longer pass any check
  via the runtime bypass.

  This migration:
  1. Grants every code currently in users.permissions to super_admin
     EXCEPT `users:grant_superadmin` (A7 reserves it for future use).
  2. Grants every code in users.permissions to admin EXCEPT
     `users:grant_superadmin`.
  3. Both INSERTs use ON CONFLICT DO NOTHING — idempotent.

  Per A7, `users:grant_superadmin` is left declared in the catalog but
  granted to NO role (including super_admin) at this time. The
  reserved-grant guard logic at permission_service.py:114 and
  role_service.py:161,170,181 stays in place to prevent runtime grants.

  Per A19, this migration implements a real downgrade.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r005_admin_explicit_grants"
down_revision: str = "r004_finance_field_perm"
branch_labels = None
depends_on = None


_RESERVED_CODES = ("users:grant_superadmin",)


def upgrade() -> None:
    bind = op.get_bind()

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles WHERE name IN ('super_admin', 'admin')"
    )).fetchall()
    role_id_by_name = {n: i for n, i in role_rows}

    super_admin_id = role_id_by_name.get("super_admin")
    admin_id = role_id_by_name.get("admin")

    if super_admin_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            WHERE code <> ALL(:reserved)
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": super_admin_id, "reserved": list(_RESERVED_CODES)})

    if admin_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            WHERE code <> ALL(:reserved)
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": admin_id, "reserved": list(_RESERVED_CODES)})


def downgrade() -> None:
    """Best-effort revert of r005's grants.

    Deletes every role_permission row for admin and super_admin, then
    re-applies r002's grant rule so the roles are not locked out.
    Idempotent: missing rows are silently no-op'd by DELETE.

    NOTE: this downgrade also reverts any grants that r002 (or earlier
    migrations) added to admin/super_admin, since we cannot distinguish
    which migration originally inserted each row. The re-apply at the
    end restores the r002 state (super_admin holds every code; admin
    holds every code except `users:grant_superadmin`).
    """
    bind = op.get_bind()

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles WHERE name IN ('super_admin', 'admin')"
    )).fetchall()
    role_id_by_name = {n: i for n, i in role_rows}

    super_admin_id = role_id_by_name.get("super_admin")
    admin_id = role_id_by_name.get("admin")

    for rid in (super_admin_id, admin_id):
        if rid is None:
            continue
        bind.execute(sa.text(
            "DELETE FROM users.role_permissions WHERE role_id = :rid"
        ), {"rid": rid})

    if super_admin_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": super_admin_id})
    if admin_id is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            SELECT :rid, code FROM users.permissions
            WHERE code <> 'users:grant_superadmin'
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": admin_id})
