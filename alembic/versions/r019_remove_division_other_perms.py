"""Remove the division free-text "others" field-permission codes.

Revision ID: r019_remove_division_other_perms
Revises: r018_widen_user_code
Create Date: 2026-06-05

The project-svc dropped the division free-text "others" path
(projects.owner_other, activities.owner_division_other,
activities.concerned_division_other). The matching field-level permission
codes — seeded by r009 / r010 — are now orphaned, so remove their grants
and the catalog rows.

Idempotent. Downgrade re-creates the permission rows (built-in) but NOT
the role grants — they are reconstructed by the seed migrations if ever
replayed.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r019_remove_division_other_perms"
down_revision: str = "r018_widen_user_code"
branch_labels = None
depends_on = None


_CODES = (
    "projects:update:owner_other",
    "activities:update:owner_division_other",
    "activities:update:concerned_division_other",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM users.role_permissions "
            "WHERE permission_code = ANY(:codes)"
        ),
        {"codes": list(_CODES)},
    )
    bind.execute(
        sa.text("DELETE FROM users.permissions WHERE code = ANY(:codes)"),
        {"codes": list(_CODES)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    for code in _CODES:
        bind.execute(
            sa.text(
                "INSERT INTO users.permissions (code, name, description, is_builtin) "
                "VALUES (:c, :c, :c, true) ON CONFLICT (code) DO NOTHING"
            ),
            {"c": code},
        )
