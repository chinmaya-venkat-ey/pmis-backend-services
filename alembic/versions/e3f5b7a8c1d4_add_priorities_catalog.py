"""doc 41 — priorities catalog + activities.priority column

Revision ID: e3f5b7a8c1d4
Revises: d2c4f8a9e1b3
Create Date: 2026-05-07

Adds a new master catalog ``priorities`` (mirrors the
``activity_status`` / ``milestone_status`` pattern) with three
built-in seed rows (``p1`` / ``p2`` / ``p3``), and adds a new
``activities.priority`` column that references the catalog code as
a string. Existing activity rows are backfilled to ``p3`` (the
"low" default).

Idempotent — checks current state before each step.
"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "e3f5b7a8c1d4"
down_revision: Union[str, Sequence[str], None] = "d2c4f8a9e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ---- 1. Create the priorities catalog ----
    if "priorities" not in existing_tables:
        op.create_table(
            "priorities",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("code", sa.String(length=16), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "active", sa.Boolean(), nullable=False, server_default=sa.true(),
            ),
            sa.Column(
                "is_builtin",
                sa.Boolean(), nullable=False, server_default=sa.false(),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("code", name="uq_priorities_code"),
        )
        op.create_index(
            "idx_priorities_active_code", "priorities", ["active", "code"],
        )

    # ---- 2. Seed p1 / p2 / p3 (idempotent) ----
    seeds = (
        ("p1", "p1", "High priority", 1),
        ("p2", "p2", "Medium priority", 2),
        ("p3", "p3", "Low priority (default)", 3),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing_codes = {
        r[0] for r in bind.execute(
            sa.text("SELECT code FROM priorities")
        ).fetchall()
    }
    for code, name, desc, pos in seeds:
        if code in existing_codes:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO priorities "
                "(id, code, name, description, position, active, is_builtin, "
                " created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :position, :active, "
                "        :is_builtin, :created_at, :updated_at)"
            ),
            {
                "id": str(uuid4()), "code": code, "name": name,
                "description": desc, "position": pos,
                "active": True, "is_builtin": True,
                "created_at": now, "updated_at": now,
            },
        )

    # ---- 3. Add the activities.priority column + backfill ----
    activity_cols = _existing_columns(inspector, "activities")
    if activity_cols and "priority" not in activity_cols:
        op.add_column(
            "activities",
            sa.Column("priority", sa.String(length=16), nullable=True),
        )
        op.create_index(
            "idx_activities_priority", "activities", ["priority"],
        )
        # Backfill: every existing activity gets the default 'p3'.
        bind.execute(
            sa.text(
                "UPDATE activities SET priority = 'p3' WHERE priority IS NULL"
            )
        )


def downgrade() -> None:
    """Intentional no-op — keeps the new column / catalog for safety."""
    pass
