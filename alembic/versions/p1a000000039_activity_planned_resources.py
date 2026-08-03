"""Move planned resources onto activities.

Revision ID: p1a000000039
Revises: p1a000000038
Create Date: 2026-07-31

Why:
  Resource costing moves off the finance-page ``planned_resources`` (a table hung
  off a resource_cost cost item, priced from a client rate card by fractional
  months) ONTO the activity. Each resource-based activity gets a 1:many set of
  allocation rows ``{ designation, quantity, duration }`` (duration a flat number
  of months in [0,3]); the monthly rate is resolved from the Java designation-rates
  service AT WRITE TIME and snapshotted here (`monthly_rate`, `computed_cost`), so
  reads + finance never call it. Create ``activity_planned_resources`` and drop the
  obsolete ``planned_resources``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p1a000000039"
down_revision = "p1a000000038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_planned_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("activity_id", sa.String(36), sa.ForeignKey("project.activities.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("designation", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("duration", sa.Numeric(4, 2), nullable=False),
        # Snapshots resolved from the Java designation-rates service at write time.
        sa.Column("monthly_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("computed_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity >= 1", name="ck_activity_planned_res_qty_positive"),
        sa.CheckConstraint("duration >= 0 AND duration <= 3", name="ck_activity_planned_res_duration_range"),
        schema="project",
    )
    op.create_index("idx_activity_planned_res_activity_live", "activity_planned_resources", ["activity_id", "deleted_at"], schema="project")
    op.create_index("idx_activity_planned_res_project_live", "activity_planned_resources", ["project_id", "deleted_at"], schema="project")
    op.create_index("ix_activity_planned_res_deleted_at", "activity_planned_resources", ["deleted_at"], schema="project")

    # Drop the obsolete finance-page planned_resources table.
    op.drop_table("planned_resources", schema="project")


def downgrade() -> None:
    # Recreate planned_resources as it stood at p1a000000038 (rate-card model).
    op.create_table(
        "planned_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("cost_item_id", sa.String(36), sa.ForeignKey("project.project_cost_items.id"), nullable=False),
        sa.Column("role", sa.String(255), nullable=True),
        sa.Column("vendor_id", sa.String(36), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("deploy_start", sa.Date(), nullable=True),
        sa.Column("deploy_end", sa.Date(), nullable=True),
        sa.Column("rate_card_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("cost_by_year", postgresql.JSONB(), nullable=True),
        sa.Column("duration_months", sa.Numeric(12, 2), nullable=True),
        sa.Column("computed_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index("idx_planned_res_project_live", "planned_resources", ["project_id", "deleted_at"], schema="project")
    op.create_index("idx_planned_res_cost_item_live", "planned_resources", ["cost_item_id", "deleted_at"], schema="project")
    op.create_index("uq_planned_res_project_position_live", "planned_resources", ["project_id", "position"], unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_planned_res_deleted_at", "planned_resources", ["deleted_at"], schema="project")

    op.drop_index("ix_activity_planned_res_deleted_at", table_name="activity_planned_resources", schema="project")
    op.drop_index("idx_activity_planned_res_project_live", table_name="activity_planned_resources", schema="project")
    op.drop_index("idx_activity_planned_res_activity_live", table_name="activity_planned_resources", schema="project")
    op.drop_table("activity_planned_resources", schema="project")
