"""Planned start/end + actual-end date-change remarks on projects.

Revision ID: p1a000000040
Revises: p1a000000039
Create Date: 2026-08-10

Additive, nullable columns mirroring #322's ``actual_start_remarks`` — the
reason/remarks captured when a project's PLANNED start, PLANNED end, or ACTUAL
end date is edited. Attachments reuse the project attachment path, tagged by
category ``planned_start_reason`` / ``planned_end_reason`` / ``actual_end_reason``
(see ProjectController). Optional (nullable) — the requirement is enforced by
the FE, matching how ``actual_start_remarks`` works today.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000040"
down_revision: str = "p1a000000039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects",
                  sa.Column("start_date_remarks", sa.String(2000), nullable=True),
                  schema="project")
    op.add_column("projects",
                  sa.Column("end_date_remarks", sa.String(2000), nullable=True),
                  schema="project")
    op.add_column("projects",
                  sa.Column("actual_end_remarks", sa.String(2000), nullable=True),
                  schema="project")


def downgrade() -> None:
    op.drop_column("projects", "actual_end_remarks", schema="project")
    op.drop_column("projects", "end_date_remarks", schema="project")
    op.drop_column("projects", "start_date_remarks", schema="project")
