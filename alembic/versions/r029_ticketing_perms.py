"""Seed ticketing / escalation / workflow permission codes + pmis_support role.

Revision ID: r029_ticketing_perms
Revises: r028_project_config_perm
Create Date: 2026-07-09

The ticketing service is a new PEP: it calls /api/v3/authz/context and enforces
these codes locally. This migration makes them known to the PDP (user-svc) so
/authz/context returns them:

  1. Seeds the 8 codes into users.permissions (canonical: app/core/permissions.py
     ALL_TICKETING_PERMISSIONS; fresh DBs get them via u1a000000002).
  2. Ensures the `pmis_support` role exists (it did not before) and grants it the
     codes — the operational owner.
  3. Also grants them to super_admin + admin: post-A1 there is NO admin short-
     circuit, so admin tiers pass a gate ONLY by holding the code explicitly.

All role grants are GLOBAL (role_permissions) → the codes land in the flat
`permissions[]` of /authz/context. Idempotent throughout.

Per A19, real downgrade implemented (the pmis_support role is left in place so
its user assignments are never orphaned).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r029_ticketing_perms"
down_revision: str = "r028_project_config_perm"
branch_labels = None
depends_on = None

_CODES = (
    "tickets:assign",
    "tickets:reassign",
    "tickets:send_back",
    "tickets:start_progress",
    "tickets:resolve",
    "tickets:bulk_update",
    "escalation_matrix:update",
    "workflow:update",
)
_GRANTEE_ROLES = ("pmis_support", "super_admin", "admin")


def _ensure_role(bind, name: str, description: str) -> None:
    exists = bind.execute(
        sa.text("SELECT 1 FROM users.roles WHERE name = :n"), {"n": name}
    ).first()
    if not exists:
        bind.execute(sa.text(
            "INSERT INTO users.roles (name, description, builtin, created_at) "
            "VALUES (:n, :d, true, NOW())"
        ), {"n": name, "d": description})


def upgrade() -> None:
    bind = op.get_bind()

    # 1. catalog
    for code in _CODES:
        bind.execute(sa.text("""
            INSERT INTO users.permissions (code, name, description, is_builtin)
            VALUES (:code, :code, :code, true)
            ON CONFLICT (code) DO NOTHING
        """), {"code": code})

    # 2. operational role
    _ensure_role(bind, "pmis_support", "PMIS support desk — ticketing operations")

    # 3. grants (pmis_support + admin tiers)
    role_ids = bind.execute(sa.text(
        "SELECT id FROM users.roles WHERE name = ANY(:names)"
    ), {"names": list(_GRANTEE_ROLES)}).fetchall()
    for (rid,) in role_ids:
        for code in _CODES:
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": rid, "code": code})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM users.role_permissions WHERE permission_code = ANY(:codes)"
    ), {"codes": list(_CODES)})
    bind.execute(sa.text(
        "DELETE FROM users.user_permissions WHERE permission_code = ANY(:codes)"
    ), {"codes": list(_CODES)})
    bind.execute(sa.text(
        "DELETE FROM users.permissions WHERE code = ANY(:codes)"
    ), {"codes": list(_CODES)})
    # pmis_support role intentionally left in place (may carry user assignments).
