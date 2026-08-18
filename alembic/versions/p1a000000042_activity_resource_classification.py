"""resource_classification on resource-based-milestone activities.

Revision ID: p1a000000042
Revises: p1a000000041
Create Date: 2026-08-18

Adds ``resource_classification`` ('planned' | 'additional') to
``project.activities`` — whether a resource-based activity's resources are part
of the original plan ('planned') or brought in beyond it ('additional', RFP
§5.28 additional resources). NULL for non-resource-based activities.

Backfill: every existing activity under a resource-based milestone was, by
definition, a PLANNED resource ('additional' is the new concept), so they are
set to 'planned'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000042"
down_revision: str = "p1a000000041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("resource_classification", sa.String(length=12), nullable=True),
        schema="project",
    )
    op.create_check_constraint(
        "ck_activities_resource_classification",
        "activities",
        "resource_classification IS NULL "
        "OR resource_classification IN ('planned', 'additional')",
        schema="project",
    )
    # Existing activities under a resource-based milestone were all PLANNED.
    op.execute(
        """
        UPDATE project.activities a
           SET resource_classification = 'planned'
          FROM project.milestones m
         WHERE a.milestone_id = m.id
           AND m.is_resource_based = true
           AND a.resource_classification IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_activities_resource_classification", "activities",
        schema="project", type_="check",
    )
    op.drop_column("activities", "resource_classification", schema="project")
