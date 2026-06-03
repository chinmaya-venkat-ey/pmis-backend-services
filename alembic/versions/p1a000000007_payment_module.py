"""Payment module tables: cost items, cost-item↔milestone, payment terms, phase QRG.

Revision ID: p1a000000007
Revises: p1a000000006
Create Date: 2026-06-03

Why:
  The Project-Finance ("payment") wizard step (Project Details → Milestone →
  Finance) needs four project-owned tables:

    - project_cost_items     — the "Project Cost" table rows. Each row has a
                               cost_type_code (logical FK masters.cost_types),
                               an optional phase (free integer; NULL for
                               one-time), cost (excl-tax) and tax_percent.
                               At most one live one-time row per project.
    - cost_item_milestones   — M:N binding a fixed cost row to a bundle of
                               milestones.
    - project_payment_terms  — the "Project Term" rows: per (phase, milestone)
                               a frequency_code + percent_of_payment. A
                               milestone is paid once per project.
    - project_phase_qrg      — per-phase "QRG Applied" boolean.

  All money columns are NUMERIC(18, 2) (INR rupees); percents NUMERIC(5, 2).
  Derived figures (row total, payment value, QRG value/%, CCN value,
  contract/summary totals) are computed on response — never stored. Every
  value field is nullable for now (mandatory rules land later, per
  requirement). The CCN cap % reuses the existing projects.ccn_cap_percent
  column (no new column here).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000007"
down_revision: str = "p1a000000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------ project_cost_items
    op.create_table(
        "project_cost_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("cost_type_code", sa.String(32), nullable=True),
        sa.Column("phase", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("tax_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index("idx_cost_items_project_live", "project_cost_items", ["project_id", "deleted_at"], schema="project")
    op.create_index("idx_cost_items_project_position", "project_cost_items", ["project_id", "position"], schema="project")
    op.create_index(
        "uq_cost_items_project_position_live", "project_cost_items", ["project_id", "position"],
        unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_cost_items_one_time_per_project_live", "project_cost_items", ["project_id"],
        unique=True, schema="project",
        postgresql_where=sa.text("cost_type_code = 'one_time' AND deleted_at IS NULL"),
    )
    op.create_index("ix_cost_items_cost_type_code", "project_cost_items", ["cost_type_code"], schema="project")
    op.create_index("ix_cost_items_deleted_at", "project_cost_items", ["deleted_at"], schema="project")
    # One-time rows carry no phase.
    op.create_check_constraint(
        "ck_cost_items_one_time_no_phase",
        "project_cost_items",
        "cost_type_code IS DISTINCT FROM 'one_time' OR phase IS NULL",
        schema="project",
    )
    op.create_check_constraint(
        "ck_cost_items_cost_nonneg", "project_cost_items",
        "cost IS NULL OR cost >= 0", schema="project",
    )
    op.create_check_constraint(
        "ck_cost_items_tax_range", "project_cost_items",
        "tax_percent IS NULL OR (tax_percent >= 0 AND tax_percent <= 100)", schema="project",
    )

    # ------------------------------------------------------------ cost_item_milestones
    op.create_table(
        "cost_item_milestones",
        sa.Column("cost_item_id", sa.String(36), sa.ForeignKey("project.project_cost_items.id"), primary_key=True),
        sa.Column("milestone_id", sa.String(36), sa.ForeignKey("project.milestones.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="project",
    )
    op.create_index("ix_cost_item_milestones_cost_item_id", "cost_item_milestones", ["cost_item_id"], schema="project")
    op.create_index("ix_cost_item_milestones_milestone_id", "cost_item_milestones", ["milestone_id"], schema="project")

    # ------------------------------------------------------------ project_payment_terms
    op.create_table(
        "project_payment_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=True),
        sa.Column("milestone_id", sa.String(36), sa.ForeignKey("project.milestones.id"), nullable=True),
        sa.Column("frequency_code", sa.String(32), nullable=True),
        sa.Column("percent_of_payment", sa.Numeric(5, 2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index("idx_payment_terms_project_live", "project_payment_terms", ["project_id", "deleted_at"], schema="project")
    op.create_index("idx_payment_terms_project_phase", "project_payment_terms", ["project_id", "phase"], schema="project")
    op.create_index(
        "uq_payment_terms_project_position_live", "project_payment_terms", ["project_id", "position"],
        unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_payment_terms_project_milestone_live", "project_payment_terms", ["project_id", "milestone_id"],
        unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_payment_terms_milestone_id", "project_payment_terms", ["milestone_id"], schema="project")
    op.create_index("ix_payment_terms_deleted_at", "project_payment_terms", ["deleted_at"], schema="project")
    op.create_check_constraint(
        "ck_payment_terms_percent_range", "project_payment_terms",
        "percent_of_payment IS NULL OR (percent_of_payment >= 0 AND percent_of_payment <= 100)",
        schema="project",
    )

    # ------------------------------------------------------------ project_phase_qrg
    op.create_table(
        "project_phase_qrg",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("qrg_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index("idx_phase_qrg_project_live", "project_phase_qrg", ["project_id", "deleted_at"], schema="project")
    op.create_index(
        "uq_phase_qrg_project_phase_live", "project_phase_qrg", ["project_id", "phase"],
        unique=True, schema="project", postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("project_phase_qrg", schema="project")
    op.drop_table("project_payment_terms", schema="project")
    op.drop_table("cost_item_milestones", schema="project")
    op.drop_table("project_cost_items", schema="project")
