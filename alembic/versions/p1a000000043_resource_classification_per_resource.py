"""Move resource_classification from activities to activity_planned_resources.

Revision ID: p1a000000043
Revises: p1a000000042
Create Date: 2026-08-19

``resource_classification`` ('planned' | 'additional') belongs PER RESOURCE, not
per activity — a single resource-based activity can mix planned resources and
ADDITIONAL ones (RFP §5.28 additional / CCN resources). This moves the attribute
onto each ``project.activity_planned_resources`` allocation row (each resource
member carries it) and drops the misplaced ``project.activities`` column added in
p1a000000042.

Backfill: every existing allocation row was, by definition, a PLANNED resource
('additional' is the new concept), so the NOT NULL ``server_default='planned'``
sets them all.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000043"
down_revision: str = "p1a000000042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Per-resource classification — existing rows backfill to 'planned' via default.
    op.add_column(
        "activity_planned_resources",
        sa.Column(
            "resource_classification", sa.String(length=12),
            nullable=False, server_default="planned",
        ),
        schema="project",
    )
    op.create_check_constraint(
        "ck_activity_planned_res_classification",
        "activity_planned_resources",
        "resource_classification IN ('planned', 'additional')",
        schema="project",
    )
    # 2. Drop the misplaced activity-level column + its constraint.
    op.drop_constraint(
        "ck_activities_resource_classification", "activities",
        schema="project", type_="check",
    )
    op.drop_column("activities", "resource_classification", schema="project")


def downgrade() -> None:
    # Restore the activity-level column + backfill resource-based-milestone activities.
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
    op.drop_constraint(
        "ck_activity_planned_res_classification", "activity_planned_resources",
        schema="project", type_="check",
    )
    op.drop_column(
        "activity_planned_resources", "resource_classification", schema="project",
    )
