"""Planned deployment date on activity planned-resource allocation rows.

Revision ID: p1a000000041
Revises: p1a000000040
Create Date: 2026-08-14

REQUIRED calendar-date column on ``project.activity_planned_resources``. Captured
alongside ``quantity`` and ``duration`` at create/edit time. One date per row:
deploying N of a designation on the same day is one row with ``quantity = N``; a
split across dates is separate rows (e.g. qty 2 on date A + qty 1 on date B).

Added NOT NULL. Because the column can't be null and rows may already exist, this
adds it nullable first, backfills every existing row with its activity's planned
start date (the sensible planned-deployment proxy; ``CURRENT_DATE`` as a last
resort for any orphan row), then sets NOT NULL. Going forward the API requires it.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000041"
down_revision: str = "p1a000000040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activity_planned_resources",
        sa.Column("planned_deployment_date", sa.Date(), nullable=True),
        schema="project",
    )
    # Backfill existing rows so the NOT NULL below can be applied: use the
    # allocation's activity planned start date, falling back to CURRENT_DATE.
    op.execute(
        """
        UPDATE project.activity_planned_resources apr
           SET planned_deployment_date = COALESCE(
                 (SELECT a.start_date::date
                    FROM project.activities a
                   WHERE a.id = apr.activity_id),
                 CURRENT_DATE)
         WHERE apr.planned_deployment_date IS NULL
        """
    )
    op.alter_column(
        "activity_planned_resources", "planned_deployment_date",
        existing_type=sa.Date(), nullable=False, schema="project",
    )


def downgrade() -> None:
    op.drop_column(
        "activity_planned_resources", "planned_deployment_date", schema="project",
    )
