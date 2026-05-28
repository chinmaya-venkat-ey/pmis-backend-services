"""Add activity_started flag to activities.

Revision ID: p1a000000005
Revises: p1a000000004
Create Date: 2026-05-28

Why:
  New boolean ``activity_started`` on ``project.activities``. NOT NULL with
  server default ``false`` so existing rows backfill to "not started" and
  any future inserts that omit the column also default to false. The field
  is gated by the field-level permission ``activities:update:activity_started``
  on PATCH; create allows any role since unset → false.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000005"
down_revision: str = "p1a000000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities", schema="project") as batch:
        batch.add_column(
            sa.Column(
                "activity_started",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("activities", schema="project") as batch:
        batch.drop_column("activity_started")
