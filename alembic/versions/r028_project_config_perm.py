"""Seed ``projects:update:config`` and grant it to the project-edit roles.

Revision ID: r028_project_config_perm
Revises: r027_payment_read_perm
Create Date: 2026-07-09

New per-project config/checks bag (``project.projects.config``, half-day hours,
attendance/leave policy flags, ...) is written via
``PUT /projects/{uuid}/config``, gated in project-svc by
``projects:update:config``. This seeds the code and grants it to exactly the
roles that already hold ``projects:update:name`` — i.e. whoever can edit a
project can also set its config — so admins AND project-edit roles pass. New
grants are additive; ``ON CONFLICT DO NOTHING`` keeps it idempotent.

Per A19, real downgrade implemented.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r028_project_config_perm"
down_revision: str = "r027_payment_read_perm"
branch_labels = None
depends_on = None

_CODE = "projects:update:config"
# Anchor: grant the new code to the same roles that already hold this one.
_ANCHOR = "projects:update:name"


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("""
        INSERT INTO users.permissions (code, name, description, is_builtin)
        VALUES (:code, :code, :code, true)
        ON CONFLICT (code) DO NOTHING
    """), {"code": _CODE})

    # Mirror the anchor code's role grants onto the new code.
    bind.execute(sa.text("""
        INSERT INTO users.role_permissions (role_id, permission_code)
        SELECT role_id, :code
        FROM users.role_permissions
        WHERE permission_code = :anchor
        ON CONFLICT (role_id, permission_code) DO NOTHING
    """), {"code": _CODE, "anchor": _ANCHOR})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM users.role_permissions WHERE permission_code = :code"
    ), {"code": _CODE})
    bind.execute(sa.text(
        "DELETE FROM users.user_permissions WHERE permission_code = :code"
    ), {"code": _CODE})
    bind.execute(sa.text(
        "DELETE FROM users.permissions WHERE code = :code"
    ), {"code": _CODE})
