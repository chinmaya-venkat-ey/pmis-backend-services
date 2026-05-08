"""user-service drift port — add columns the monolith already has

Revision ID: b9f4d27e1a83
Revises: 7e3fa9c21b4d
Create Date: 2026-05-01

Adds the following columns to ``users``, each present in the monolith
but missing from the user-service initial schema:

  - vendor_id                                  (FK to vendors.id, nullable)
  - division                                   (String(32), nullable)
  - division_other                             (String(255), nullable)
  - deleted_at                                 (DateTime, nullable, indexed)
  - deleted_by                                 (FK to users.id, nullable)
  - previous_refresh_token_jti                 (String(64), nullable)
  - previous_refresh_token_jti_valid_until     (DateTime, nullable)

IDEMPOTENT — every column is added only when absent. The shared-Postgres
deployment already has these columns (the monolith added them); on a
fresh DB they're created. Same pattern as 7e3fa9c21b4d.

Indexes are added only when their column was just created (or when an
existing column lacks the index). FKs are added with ``use_alter=True`` so
the vendors table can be created independently.

DOWNGRADE is intentionally a no-op — the columns are shared with the
monolith and dropping them would break it. Real cleanup happens in a
dedicated decommissioning migration when the monolith is retired.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9f4d27e1a83"
down_revision: Union[str, Sequence[str], None] = "7e3fa9c21b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table: str) -> set:
    return {c["name"] for c in inspector.get_columns(table)}


def _existing_indexes(inspector, table: str) -> set:
    return {i["name"] for i in inspector.get_indexes(table)}


def _existing_fks(inspector, table: str) -> set:
    return {fk.get("name") for fk in inspector.get_foreign_keys(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "users" not in set(inspector.get_table_names()):
        # Initial migration didn't run on this DB — nothing to alter.
        return

    user_cols = _existing_columns(inspector, "users")
    user_idx = _existing_indexes(inspector, "users")
    user_fks = _existing_fks(inspector, "users")

    # ---- Add columns ----------------------------------------------------
    if "vendor_id" not in user_cols:
        op.add_column(
            "users",
            sa.Column("vendor_id", sa.String(length=36), nullable=True),
        )
    if "division" not in user_cols:
        op.add_column(
            "users",
            sa.Column("division", sa.String(length=32), nullable=True),
        )
    if "division_other" not in user_cols:
        op.add_column(
            "users",
            sa.Column("division_other", sa.String(length=255), nullable=True),
        )
    if "deleted_at" not in user_cols:
        op.add_column(
            "users",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    if "deleted_by" not in user_cols:
        op.add_column(
            "users",
            sa.Column("deleted_by", sa.Integer(), nullable=True),
        )
    if "previous_refresh_token_jti" not in user_cols:
        op.add_column(
            "users",
            sa.Column(
                "previous_refresh_token_jti",
                sa.String(length=64),
                nullable=True,
            ),
        )
    if "previous_refresh_token_jti_valid_until" not in user_cols:
        op.add_column(
            "users",
            sa.Column(
                "previous_refresh_token_jti_valid_until",
                sa.DateTime(),
                nullable=True,
            ),
        )

    # Re-inspect after add_column so subsequent index / FK checks see the
    # freshly-created columns.
    inspector = sa.inspect(bind)
    user_idx = _existing_indexes(inspector, "users")
    user_fks = _existing_fks(inspector, "users")

    # ---- Indexes (column-attached) -------------------------------------
    if "idx_users_deleted_at" not in user_idx:
        op.create_index(
            "idx_users_deleted_at", "users", ["deleted_at"], unique=False,
        )
    if "idx_users_vendor_id" not in user_idx:
        op.create_index(
            "idx_users_vendor_id", "users", ["vendor_id"], unique=False,
        )
    if "idx_users_created_at" not in user_idx:
        op.create_index(
            "idx_users_created_at", "users", ["created_at"], unique=False,
        )

    # ---- Foreign keys (added late via use_alter pattern) ---------------
    # vendors and users may be created in any order; declare FKs last.
    if "fk_users_vendor_id" not in user_fks:
        # Skip silently if vendors table is absent (would happen on a
        # truly fresh DB before the project-service migration runs).
        if "vendors" in set(inspector.get_table_names()):
            op.create_foreign_key(
                "fk_users_vendor_id",
                source_table="users",
                referent_table="vendors",
                local_cols=["vendor_id"],
                remote_cols=["id"],
            )

    if "fk_users_deleted_by_users" not in user_fks:
        op.create_foreign_key(
            "fk_users_deleted_by_users",
            source_table="users",
            referent_table="users",
            local_cols=["deleted_by"],
            remote_cols=["id"],
        )


def downgrade() -> None:
    """Intentionally a no-op — see module docstring."""
    pass
