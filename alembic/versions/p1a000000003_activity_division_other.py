"""Add owner_division_other + concerned_division_other to activities.

Revision ID: p1a000000003_activity_division_other
Revises: p1a000000002_team_management
Create Date: 2026-05-25

Why:
  When an activity's owner_division is set to the catalog code 'others'
  (or concerned_divisions includes 'others'), the FE needs to capture a
  free-text label describing which "other" division is meant. This
  mirrors the existing project-level pattern (project.owner='others' +
  project.owner_other free text) and the user-level pattern
  (user.division='others' + user.division_other).

  Two new nullable VARCHAR(255) columns:
    activities.owner_division_other
    activities.concerned_division_other

  Existing rows keep both as NULL (no backfill needed). New rows enforce
  the 'others-with-text' / 'non-others-without-text' invariant at the
  service layer.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000003"
down_revision: str = "p1a000000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities", schema="project") as batch:
        batch.add_column(
            sa.Column("owner_division_other", sa.String(length=255), nullable=True)
        )
        batch.add_column(
            sa.Column("concerned_division_other", sa.String(length=255), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("activities", schema="project") as batch:
        batch.drop_column("concerned_division_other")
        batch.drop_column("owner_division_other")
