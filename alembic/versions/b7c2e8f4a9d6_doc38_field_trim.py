"""doc 38 — field trim across activity / task / subtask

Revision ID: b7c2e8f4a9d6
Revises: d3e5f7a9b1c2
Create Date: 2026-05-07

Combines the three doc-38 monolith migrations
(``e8d4f7a2b9c1`` + ``f1e8d6a4b9c2`` + ``a3f5b2c8d4e1``) into a single
project-service migration. Idempotent — every block checks current
state before altering, so it's a no-op against the shared Postgres
where the monolith already applied these changes.

Net schema effect:

  activities
    - ADD COLUMN owner_division     VARCHAR(32)  NULL  + index
    - ADD COLUMN concerned_division VARCHAR(32)  NULL  + index
    - ADD COLUMN vendor_id          VARCHAR(36)  NULL  + index + FK to vendors.id
    - ALTER COLUMN type DROP NOT NULL
    - Relax ck_activities_type to allow NULL

  tasks, subtasks
    - ALTER COLUMN type DROP NOT NULL
    - Relax ck_<table>_type to allow NULL
    - ADD COLUMN status VARCHAR(32) NULL + index

Downgrade is intentionally a no-op (additive migration; matches
project-service convention since all M/A/T/S tables are shared
infrastructure with the monolith).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c2e8f4a9d6"
down_revision: Union[str, Sequence[str], None] = "d3e5f7a9b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # ---------------------------------------------------------------
    # activities — 3 new columns + drop NOT NULL on type + relax CHECK
    # ---------------------------------------------------------------
    cols = _existing_columns(inspector, "activities")
    if cols:
        if "owner_division" not in cols:
            op.add_column(
                "activities",
                sa.Column("owner_division", sa.String(length=32), nullable=True),
            )
            try:
                op.create_index(
                    "ix_activities_owner_division",
                    "activities", ["owner_division"], unique=False,
                )
            except Exception:
                pass

        if "concerned_division" not in cols:
            op.add_column(
                "activities",
                sa.Column("concerned_division", sa.String(length=32), nullable=True),
            )
            try:
                op.create_index(
                    "ix_activities_concerned_division",
                    "activities", ["concerned_division"], unique=False,
                )
            except Exception:
                pass

        if "vendor_id" not in cols:
            op.add_column(
                "activities",
                sa.Column("vendor_id", sa.String(length=36), nullable=True),
            )
            try:
                op.create_index(
                    "ix_activities_vendor_id",
                    "activities", ["vendor_id"], unique=False,
                )
            except Exception:
                pass
            if dialect == "postgresql":
                try:
                    op.create_foreign_key(
                        "fk_activities_vendor_id",
                        "activities", "vendors",
                        ["vendor_id"], ["id"],
                    )
                except Exception:
                    pass

        if "type" in cols and not cols["type"].get("nullable"):
            if dialect == "postgresql":
                op.execute(
                    "ALTER TABLE activities ALTER COLUMN type DROP NOT NULL"
                )
            else:
                try:
                    with op.batch_alter_table("activities") as batch:
                        batch.alter_column("type", nullable=True)
                except Exception:
                    pass

        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE activities DROP CONSTRAINT IF EXISTS ck_activities_type"
            )
            op.execute(
                "ALTER TABLE activities ADD CONSTRAINT ck_activities_type "
                "CHECK (type IS NULL OR type IN "
                "('standard', 'resource', 'transactional'))"
            )

    # ---------------------------------------------------------------
    # tasks + subtasks — drop NOT NULL on type, add status, relax CHECK
    # ---------------------------------------------------------------
    for table in ("tasks", "subtasks"):
        cols = _existing_columns(inspector, table)
        if not cols:
            continue

        if "type" in cols and not cols["type"].get("nullable"):
            if dialect == "postgresql":
                op.execute(
                    f"ALTER TABLE {table} ALTER COLUMN type DROP NOT NULL"
                )
            else:
                try:
                    with op.batch_alter_table(table) as batch:
                        batch.alter_column("type", nullable=True)
                except Exception:
                    pass

        if "status" not in cols:
            op.add_column(
                table,
                sa.Column("status", sa.String(length=32), nullable=True),
            )
            try:
                op.create_index(
                    f"idx_{table}_status", table, ["status"], unique=False,
                )
            except Exception:
                pass

        if dialect == "postgresql":
            op.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_type"
            )
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_type "
                f"CHECK (type IS NULL OR type IN "
                f"('standard', 'resource', 'transactional'))"
            )


def downgrade() -> None:
    """Intentional no-op (additive migration; M/A/T/S tables are shared
    infrastructure)."""
    pass
