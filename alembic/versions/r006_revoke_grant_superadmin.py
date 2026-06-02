"""Revoke users:grant_superadmin from every role (A7 reserved code).

Revision ID: r006_revoke_grant_superadmin
Revises: r005_admin_explicit_grants
Create Date: 2026-06-02

Why:
  A7 decision (permissions_decisions.md, 2026-06-02 audit cycle):
  reserve `users:grant_superadmin` for future use. No role should hold it
  today — including super_admin.

  The reserved-grant runtime guards at permission_service.py:114 and
  role_service.py:161,170,181 already prevent the runtime grant API from
  handing this code to any role, but u1a's bootstrap originally seeded
  it onto super_admin. This migration revokes that grant.

  If a future decision restores admin's (or someone else's) ability to
  grant super_admin, a new migration can re-grant this code.

  Per A19, real downgrade implemented.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r006_revoke_grant_superadmin"
down_revision: str = "r005_admin_explicit_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        DELETE FROM users.role_permissions
        WHERE permission_code = 'users:grant_superadmin'
    """))


def downgrade() -> None:
    """Restore the original grant to super_admin (u1a's original state).

    u1a granted `users:grant_superadmin` to super_admin only. This
    downgrade re-establishes that grant. Idempotent via ON CONFLICT.
    """
    bind = op.get_bind()
    super_admin_row = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = 'super_admin'"
    )).first()
    if super_admin_row is not None:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            VALUES (:rid, 'users:grant_superadmin')
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": super_admin_row[0]})
