"""Seed users:list_all_orgs permission + grant to admin / super_admin.

Revision ID: r013_users_list_orgs
Revises: r012_payment_master_perms
Create Date: 2026-06-04

Bug #213: Org Admin and Project Admin could see every organization's
users in the GET /users list because the broad-view bypass was gated on
``users:read_all`` — a code r001 grants to org_admin (so OA can read
individual user records). The two intents (read-any-user vs view-all-
orgs in the list) were conflated.

Fix: split off a dedicated ``users:list_all_orgs`` permission that
governs the system-wide list view only. The list endpoint reads this
new code; ``users:read_all`` keeps its meaning for ``GET /users/{id}``.

Grant:
  * ``users:list_all_orgs`` is granted to ``admin`` + ``super_admin``
    only. Org Admin / Project Admin keep ``users:read_all`` (individual
    fetches still work for them) but lose broad-list-view, falling back
    to vendor-scoped listings courtesy of the #174 vendor_id hydration.

Re-runnable: every INSERT uses ON CONFLICT DO NOTHING.

Per A19 a real downgrade is implemented: drop the grants, drop the
permission row.

Revision id is 22 chars — under the 32-char alembic version_num cap.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r013_users_list_orgs"
down_revision: str = "r012_payment_master_perms"
branch_labels = None
depends_on = None


_NEW_CODE = "users:list_all_orgs"
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

    # 2. Grant to admin tiers.
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
        sa.text(
            "DELETE FROM users.role_permissions WHERE permission_code = :code"
        ),
        {"code": _NEW_CODE},
    )
    bind.execute(
        sa.text("DELETE FROM users.permissions WHERE code = :code"),
        {"code": _NEW_CODE},
    )
