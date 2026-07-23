"""#365 — SuperAdmin session view + instant revoke.

1. Add ``users.refresh_tokens.access_jti`` (nullable): the jti of the ACCESS
   token minted alongside each session, so revoking a session can also denylist
   its access token in ``users.revoked_tokens`` for an instant hard cut (access
   tokens are otherwise valid until their short natural expiry).
2. Seed the ``users:revoke_sessions`` permission and grant it to super_admin
   ONLY — the gate for the session list / revoke endpoints.

Revision ID: r030_session_admin
Revises: r029_ticketing_perms
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "r030_session_admin"
down_revision: str = "r029_ticketing_perms"
branch_labels = None
depends_on = None

_NEW_CODE = "users:revoke_sessions"
_GRANTEES = ("super_admin",)


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("access_jti", sa.String(length=64), nullable=True),
        schema="users",
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO users.permissions (code, name, description, is_builtin) "
            "VALUES (:code, :code, :code, true) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": _NEW_CODE},
    )
    role_rows = bind.execute(
        sa.text("SELECT id FROM users.roles WHERE name = ANY(:names)"),
        {"names": list(_GRANTEES)},
    ).fetchall()
    for (role_id,) in role_rows:
        bind.execute(
            sa.text(
                "INSERT INTO users.role_permissions (role_id, permission_code) "
                "VALUES (:rid, :code) ON CONFLICT (role_id, permission_code) DO NOTHING"
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
    op.drop_column("refresh_tokens", "access_jti", schema="users")
