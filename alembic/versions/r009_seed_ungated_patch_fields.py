"""Seed §3.8 field codes (project active/parent_id/status + activity
category/ccn_value/owner_division_other/concerned_division_other) and
grant to admin/super_admin.

Revision ID: r009_seed_ungated_patch_fields
Revises: r008_seed_approvals_moderate
Create Date: 2026-06-02

§3.8 (2026-06-02 audit): the generic PATCH endpoint on projects/activities
accepted these columns in the Pydantic schema but the field walker had no
mapped code, so they were writable without holding ANY ``*:update:*``
code. Added codes to canonical + mirror; this migration seeds them into
``users.permissions`` and grants to admin/super_admin so they continue to
pass after A1.

Per A19, real downgrade implemented.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r009_seed_ungated_patch_fields"
down_revision: str = "r008_seed_approvals_moderate"
branch_labels = None
depends_on = None


_NEW_CODES = (
    "projects:update:active",
    "projects:update:parent_id",
    "projects:update:status",
    "activities:update:category",
    "activities:update:ccn_value",
    "activities:update:owner_division_other",
    "activities:update:concerned_division_other",
)


def upgrade() -> None:
    bind = op.get_bind()

    for code in _NEW_CODES:
        bind.execute(sa.text("""
            INSERT INTO users.permissions (code, name, description, is_builtin)
            VALUES (:code, :code, :code, true)
            ON CONFLICT (code) DO NOTHING
        """), {"code": code})

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles WHERE name IN ('super_admin', 'admin')"
    )).fetchall()
    for _name, rid in role_rows:
        for code in _NEW_CODES:
            bind.execute(sa.text("""
                INSERT INTO users.role_permissions (role_id, permission_code)
                VALUES (:rid, :code)
                ON CONFLICT (role_id, permission_code) DO NOTHING
            """), {"rid": rid, "code": code})


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("""
        DELETE FROM users.role_permissions
        WHERE permission_code = ANY(:codes)
    """), {"codes": list(_NEW_CODES)})
    bind.execute(sa.text("""
        DELETE FROM users.user_permissions
        WHERE permission_code = ANY(:codes)
    """), {"codes": list(_NEW_CODES)})
    bind.execute(sa.text("""
        DELETE FROM users.permissions
        WHERE code = ANY(:codes)
    """), {"codes": list(_NEW_CODES)})
