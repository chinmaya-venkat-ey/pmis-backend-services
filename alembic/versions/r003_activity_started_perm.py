"""Seed permission row + grants for activities:update:activity_started.

Revision ID: r003_activity_started_perm
Revises: r002_backfill_admin_perms
Create Date: 2026-05-28

Why:
  Field-level permission for the new ``activities.activity_started``
  boolean. The canonical catalog and ACTIVITY_FIELD_CODES already declare
  the constant; this migration ensures deployed DBs have the row in
  ``users.permissions`` plus role grants on the five expected tiers:

    super_admin, admin, org_admin, project_admin, project_member

  All operations use ``ON CONFLICT DO NOTHING`` — re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r003_activity_started_perm"
down_revision: str = "r002_backfill_admin_perms"
branch_labels = None
depends_on = None


_PERMISSION_CODE = "activities:update:activity_started"
_ROLES_TO_GRANT = ("super_admin", "admin", "org_admin", "project_admin", "project_member")


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "INSERT INTO users.permissions (code, name, description, is_builtin) "
            "VALUES (:code, :code, :code, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": _PERMISSION_CODE},
    )

    role_rows = bind.execute(
        sa.text("SELECT name, id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_ROLES_TO_GRANT)},
    ).fetchall()

    for _name, role_id in role_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.role_permissions (role_id, permission_code) "
                "VALUES (:rid, :code) "
                "ON CONFLICT (role_id, permission_code) DO NOTHING"
            ),
            {"rid": role_id, "code": _PERMISSION_CODE},
        )


def downgrade() -> None:
    # Intentional no-op: removing a permission that callers may rely on
    # would silently lock writes via the field-walker gate.
    pass
