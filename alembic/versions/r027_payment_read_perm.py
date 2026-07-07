"""Seed the payment:read permission and grant it to the admin tiers only.

Revision ID: r027_payment_read_perm
Revises: r026_carry_forward_method_perms
Create Date: 2026-07-07

Why:
  The Project-Finance planning page (GET /payment-page + the finance read
  endpoints) must be visible to the ADMIN tiers only. Previously those reads
  were gated by projects:read, which every project member holds. We introduce a
  dedicated code

    payment:read

  granted ONLY to super_admin / admin — deliberately NOT to org_admin /
  project_admin / project_member / division_member. project-svc swaps the
  finance read gates from projects:read to payment:read, so only the admin
  tiers can view the finance page.

  Mirrors the r016 projects:admin_override pattern (admin-only capability, not
  part of any shared bundle). All operations use ON CONFLICT DO NOTHING —
  re-runnable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "r027_payment_read_perm"
down_revision: str = "r026_carry_forward_method_perms"
branch_labels = None
depends_on = None


_CODE = "payment:read"
_GRANTEES = ("super_admin", "admin")


def _ensure_permission(bind, code: str) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO users.permissions (code, name, description, is_builtin) "
            "VALUES (:code, :code, :code, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": code},
    )


def _grant(bind, role_names, code) -> None:
    role_rows = bind.execute(
        sa.text("SELECT name, id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(role_names)},
    ).fetchall()
    for _name, role_id in role_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.role_permissions (role_id, permission_code) "
                "VALUES (:rid, :code) "
                "ON CONFLICT (role_id, permission_code) DO NOTHING"
            ),
            {"rid": role_id, "code": code},
        )


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_permission(bind, _CODE)
    _grant(bind, _GRANTEES, _CODE)


def downgrade() -> None:
    # Intentional no-op: revoking it would silently re-open the finance page.
    pass
