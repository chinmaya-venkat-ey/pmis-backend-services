"""doc 41 follow-up — assigned_to (single assignee) on tasks + subtasks
(mirror of the monolith's c8a3d4f6e9b2)

Revision ID: c8a3d4f6e9b2
Revises: e3f5b7a8c1d4
Create Date: 2026-05-08

Adds an optional single-assignee column to tasks and subtasks (subtasks
covers both top-level and nested via the same table). NULL = unassigned;
no backfill needed because pre-existing rows are simply unassigned.

Wire keyword: ``assignedTo`` (camelCase, mirrors ``vendorId``). The column
is a String(36) FK to ``users.id``, indexed for filter / list queries.

NOTE: project-service runs its own alembic chain (version table
``alembic_version_project_svc``), so this revision id can match the
monolith's id without colliding — Postgres tracks each service's
chain independently.

Idempotent — checks current state before each step so re-running on a
partially-applied DB is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8a3d4f6e9b2"
down_revision: Union[str, Sequence[str], None] = "e3f5b7a8c1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def _existing_indexes(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {i["name"] for i in inspector.get_indexes(table_name)}


def _existing_fks(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name) if fk.get("name")}


def _add_assigned_to(inspector, table: str) -> None:
    cols = _existing_columns(inspector, table)
    if not cols:
        return  # table missing entirely — nothing to do
    if "assigned_to" not in cols:
        op.add_column(
            table,
            sa.Column("assigned_to", sa.String(length=36), nullable=True),
        )

    idxs = _existing_indexes(inspector, table)
    idx_name = f"idx_{table}_assigned_to"
    if idx_name not in idxs:
        op.create_index(idx_name, table, ["assigned_to"])

    fks = _existing_fks(inspector, table)
    fk_name = f"fk_{table}_assigned_to_users"
    if fk_name not in fks:
        bind = op.get_bind()
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                fk_name, table, "users", ["assigned_to"], ["id"],
            )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("tasks", "subtasks"):
        _add_assigned_to(inspector, table)


def downgrade() -> None:
    """Intentional no-op — keep the new column for safety, mirroring
    the monolith's downgrade choice."""
    pass
