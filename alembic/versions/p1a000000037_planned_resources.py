"""Create project.planned_resources (planned-resource costing).

Revision ID: p1a000000037
Revises: p1a000000036
Create Date: 2026-07-28

Why:
  Resource-type phases cost their quarter from planned resources: rows of
  (designation, deployment window, quantity) whose cost = quantity × per-month
  rate × duration in months (the deployment window as fractional months). Each
  row rolls up into its ``resource_cost`` cost item; the SUM populates that cost
  item's ``cost``. Designation/vendor are logical FKs to masters (read via mirror).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p1a000000037"
down_revision = "p1a000000036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planned_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("cost_item_id", sa.String(36), sa.ForeignKey("project.project_cost_items.id"), nullable=False),
        sa.Column("designation_id", sa.String(36), nullable=False),
        sa.Column("vendor_id", sa.String(36), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("deploy_start", sa.Date(), nullable=True),
        sa.Column("deploy_end", sa.Date(), nullable=True),
        sa.Column("monthly_rate_snapshot", sa.Numeric(12, 2), nullable=True),
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
    op.create_index(
        "uq_planned_res_project_position_live", "planned_resources", ["project_id", "position"],
        unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_planned_res_deleted_at", "planned_resources", ["deleted_at"], schema="project")


def downgrade() -> None:
    op.drop_index("ix_planned_res_deleted_at", table_name="planned_resources", schema="project")
    op.drop_index("uq_planned_res_project_position_live", table_name="planned_resources", schema="project")
    op.drop_index("idx_planned_res_cost_item_live", table_name="planned_resources", schema="project")
    op.drop_index("idx_planned_res_project_live", table_name="planned_resources", schema="project")
    op.drop_table("planned_resources", schema="project")
