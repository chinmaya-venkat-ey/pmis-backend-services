"""Seed permission row + grants for projects:update:finance.

Revision ID: r004_finance_field_perm
Revises: r003_activity_started_perm
Create Date: 2026-06-01

Why:
  Field-level permission for the Doc-finance contract fields on
  ``project.projects`` (``total_project_value_excl_tax``, ``tax_percent``,
  ``ccn_cap_percent``). The canonical catalog + PROJECT_FIELD_CODES
  already declare the constant in app/core/permissions.py; this
  migration ensures deployed DBs have the row in ``users.permissions``
  plus role grants on the four expected tiers:

    super_admin, admin, org_admin, project_admin

  (project_member is intentionally excluded — finance is owned by the
  admin tiers + the project admin. super_admin / admin pass the gate
  via admin-bypass regardless, but we seed the explicit grant for
  hygiene.)

  All operations use ``ON CONFLICT DO NOTHING`` — re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r004_finance_field_perm"
down_revision: str = "r003_activity_started_perm"
branch_labels = None
depends_on = None


_PERMISSION_CODE = "projects:update:finance"
_ROLES_TO_GRANT = ("super_admin", "admin", "org_admin", "project_admin")


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
