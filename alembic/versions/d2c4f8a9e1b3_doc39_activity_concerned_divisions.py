"""doc 39 — activity multi concerned_divisions (JSON column with backfill)

Revision ID: d2c4f8a9e1b3
Revises: b7c2e8f4a9d6
Create Date: 2026-05-07

Adds a new ``activities.concerned_divisions`` JSON column (a list of
division codes) and backfills it from the existing single-value
``concerned_division`` column for legacy rows. The old column is
intentionally kept on disk so legacy reads still work; new writes
target only the JSON column going forward.

Idempotent — checks current state before each step.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2c4f8a9e1b3"
down_revision: Union[str, Sequence[str], None] = "b7c2e8f4a9d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = _existing_columns(inspector, "activities")
    if not cols:
        return

    if "concerned_divisions" not in cols:
        op.add_column(
            "activities",
            sa.Column("concerned_divisions", sa.JSON(), nullable=True),
        )

    # Backfill: for each row where concerned_division is set but
    # concerned_divisions is NULL, write the single value into the
    # array column. Portable over Postgres + SQLite.
    if "concerned_division" in cols:
        # The column was either just added in this migration (always NULL)
        # or already existed. Either way, IS NULL is the only universal check
        # — Postgres JSON type can't be compared to a plain string literal.
        rows = bind.execute(
            sa.text(
                "SELECT id, concerned_division FROM activities "
                "WHERE concerned_division IS NOT NULL "
                "AND concerned_divisions IS NULL"
            )
        ).fetchall()
        for row_id, single_value in rows:
            bind.execute(
                sa.text(
                    "UPDATE activities SET concerned_divisions = :v WHERE id = :id"
                ),
                {"v": json.dumps([single_value]), "id": row_id},
            )


def downgrade() -> None:
    """Intentional no-op — keeps the new column for safety. Old
    ``concerned_division`` column was never touched."""
    pass
