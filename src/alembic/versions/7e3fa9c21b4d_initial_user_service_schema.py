"""initial user-service schema (idempotent)

Revision ID: 7e3fa9c21b4d
Revises:
Create Date: 2026-04-24

Creates ``users``, ``roles``, ``revoked_tokens`` and their indexes.

IDEMPOTENT: each table is created only if absent. This matters because
in Phase 1 we share Postgres with the monolith, whose initial migration
already created these three tables. Running this migration against the
shared DB is a no-op; running it against a fresh DB creates the tables.

DOWNGRADE is intentionally a no-op: the three tables are shared
infrastructure used by the monolith as well (it reads users for FK
joins). Dropping them here would break the other service. Real cleanup
happens only after the monolith is decommissioned (Phase 6 of the
migration plan), at which point a dedicated migration will handle it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7e3fa9c21b4d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the three tables if they don't already exist in the DB."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ---- users -----------------------------------------------------------
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("login", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=255), nullable=True),
            sa.Column("last_name", sa.String(length=255), nullable=True),
            sa.Column("admin", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("refresh_token_jti", sa.String(length=64), nullable=True),
            sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("login", name="uq_users_login"),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
        op.create_index("idx_users_login", "users", ["login"], unique=False)
        op.create_index("idx_users_email", "users", ["email"], unique=False)
        op.create_index("idx_users_status", "users", ["status"], unique=False)
        op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    # ---- roles -----------------------------------------------------------
    if "roles" not in existing_tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("builtin", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_roles_name"),
        )
        op.create_index("idx_roles_name", "roles", ["name"], unique=False)
        op.create_index("idx_roles_builtin", "roles", ["builtin"], unique=False)
        op.create_index(op.f("ix_roles_id"), "roles", ["id"], unique=False)

    # ---- revoked_tokens --------------------------------------------------
    if "revoked_tokens" not in existing_tables:
        op.create_table(
            "revoked_tokens",
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("jti"),
        )
        op.create_index(
            "idx_revoked_tokens_user", "revoked_tokens", ["user_id"], unique=False,
        )
        op.create_index(
            "idx_revoked_tokens_expires", "revoked_tokens", ["expires_at"], unique=False,
        )
        op.create_index(
            op.f("ix_revoked_tokens_jti"), "revoked_tokens", ["jti"], unique=False,
        )
        op.create_index(
            op.f("ix_revoked_tokens_user_id"), "revoked_tokens", ["user_id"], unique=False,
        )
        op.create_index(
            op.f("ix_revoked_tokens_expires_at"),
            "revoked_tokens", ["expires_at"], unique=False,
        )


def downgrade() -> None:
    """Intentionally a no-op.

    See module docstring: these are shared-infra tables. Dropping them
    would break the monolith. Real teardown happens in a dedicated
    decommissioning migration after the monolith's user module is
    removed.
    """
    pass
