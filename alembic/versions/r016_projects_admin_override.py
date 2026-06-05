"""Seed projects:admin_override + grant to admin / super_admin only.

Revision ID: r016_admin_override
Revises: r015_audit_logs
Create Date: 2026-06-04

Part of the RBAC centralisation: project-management drops its `is_admin`
short-circuit and resolves authorization from user-management's
/authz/context (which carries no is_admin flag). A few genuine
"only a platform admin may do this" sites remain — editing finance after the
publish-lock, and seeing new/draft projects. Those now gate on an explicit
capability code instead of the role flag.

`projects:admin_override` is granted to admin + super_admin ONLY. It is
deliberately NOT in any project-domain bundle, so project_admin does not
receive it (preserving the "only an administrator" intent of those sites
without the drifted scoped-admin behaviour the flag had).

Re-runnable: every INSERT uses ON CONFLICT DO NOTHING.

Per A19 a real downgrade is implemented: drop the grants, drop the
permission row.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r016_admin_override"
down_revision: str = "r015_audit_logs"
branch_labels = None
depends_on = None


_NEW_CODE = "projects:admin_override"
_GRANTEES = ("admin", "super_admin")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Ensure the permission row exists (FK target for role_permissions).
    bind.execute(
        sa.text(
            "INSERT INTO users.permissions (code, name, description, is_builtin) "
            "VALUES (:code, :code, :code, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": _NEW_CODE},
    )

    # 2. Grant to admin + super_admin only.
    role_rows = bind.execute(
        sa.text("SELECT id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_GRANTEES)},
    ).fetchall()
    for (role_id,) in role_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.role_permissions (role_id, permission_code) "
                "VALUES (:rid, :code) "
                "ON CONFLICT (role_id, permission_code) DO NOTHING"
            ),
            {"rid": role_id, "code": _NEW_CODE},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM users.role_permissions WHERE permission_code = :code"),
        {"code": _NEW_CODE},
    )
    bind.execute(
        sa.text("DELETE FROM users.permissions WHERE code = :code"),
        {"code": _NEW_CODE},
    )
