"""tester report — milestone actual_start_date / actual_end_date columns
(mirror of monolith d6b9c4f8a3e1)

Revision ID: d6b9c4f8a3e1
Revises: b5e7f2a8c9d3
Create Date: 2026-05-08

Adds the two ``actual_*`` date columns to ``milestones`` so the FE can
render Actual Start Date / Actual End Date on the milestone edit form
(matching the existing activity / task / subtask shape). Both nullable;
no backfill needed because pre-existing rows are simply "no actuals
recorded yet".

NOTE: project-service runs its own alembic chain (version table
``alembic_version_project_svc``), so this revision id matches the
monolith's id without colliding. The down_revision differs (here it's
b5e7f2a8c9d3 / priority on M/T/S; in monolith it's c8a3d4f6e9b2)
because project-service's chain is shaped differently.

Idempotent — checks current state before each step so re-running on a
partially-applied DB is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6b9c4f8a3e1"
down_revision: Union[str, Sequence[str], None] = "b5e7f2a8c9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table_name: str):
    if table_name not in set(inspector.get_table_names()):
        return {}
    return {c["name"]: c for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = _existing_columns(inspector, "milestones")
    if not cols:
        return  # table missing entirely — nothing to do
    if "actual_start_date" not in cols:
        op.add_column(
            "milestones",
            sa.Column("actual_start_date", sa.DateTime(), nullable=True),
        )
    if "actual_end_date" not in cols:
        op.add_column(
            "milestones",
            sa.Column("actual_end_date", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Intentional no-op — keeps the new columns for safety, matching the
    rest of the recent doc-41 follow-up migrations."""
    pass
