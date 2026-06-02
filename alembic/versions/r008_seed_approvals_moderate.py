"""Seed approvals:moderate + grant to admin/super_admin.

Revision ID: r008_seed_approvals_moderate
Revises: r007_orphan_and_deadcode_cleanup
Create Date: 2026-06-02

§3.1 (2026-06-02 audit) item 4: ``approvals:moderate`` is the new code
that replaces the removed ``caller_is_admin`` short-circuit in
``approval_inbox_service`` for detail view, SUBMIT, and APPROVE/REJECT
transitions. Without this code in the catalog + on admin/super_admin,
those approval flows would 403 for admins after A1.

Per A19, a real downgrade is implemented.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r008_seed_approvals_moderate"
down_revision: str = "r007_orphan_and_deadcode_cleanup"
branch_labels = None
depends_on = None


_CODE = "approvals:moderate"


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("""
        INSERT INTO users.permissions (code, name, description, is_builtin)
        VALUES (:code, :code, 'Approval workflow moderator (admin tier).', true)
        ON CONFLICT (code) DO NOTHING
    """), {"code": _CODE})

    role_rows = bind.execute(sa.text(
        "SELECT name, id FROM users.roles WHERE name IN ('super_admin', 'admin')"
    )).fetchall()
    for _name, rid in role_rows:
        bind.execute(sa.text("""
            INSERT INTO users.role_permissions (role_id, permission_code)
            VALUES (:rid, :code)
            ON CONFLICT (role_id, permission_code) DO NOTHING
        """), {"rid": rid, "code": _CODE})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        DELETE FROM users.role_permissions WHERE permission_code = :code
    """), {"code": _CODE})
    bind.execute(sa.text("""
        DELETE FROM users.user_permissions WHERE permission_code = :code
    """), {"code": _CODE})
    bind.execute(sa.text("""
        DELETE FROM users.permissions WHERE code = :code
    """), {"code": _CODE})
