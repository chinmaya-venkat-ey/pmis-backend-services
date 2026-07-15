"""Add contract.sla_observations + contract.sla_evaluation_results.

Foundation for automated daily SLA evaluation:

  sla_observations       — the standing observed value per mapping (auto from
                           activity dates, or recorded via the input API).
  sla_evaluation_results — one dated result per mapping per cron run: the
                           rich status, engine output, LD money, and the
                           hybrid target/actual/delay days. This is the
                           history the dashboard + cost page aggregate.

Both cascade-delete with their SLA mapping.

Revision ID: 0020_sla_automated_evaluation
Revises: 0019_dsl_seed
Create Date: 2026-07-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0020_sla_automated_evaluation"
down_revision = "0019_dsl_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sla_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mapping_id", sa.String(36),
            sa.ForeignKey("contract.sla_activity_mappings.id", ondelete="CASCADE",
                          name="fk_sla_obs_mapping"),
            nullable=False,
        ),
        sa.Column("sla_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("metric_key", sa.String(120)),
        sa.Column("observed_value", postgresql.JSONB, nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="recorded"),
        sa.Column("period_start", sa.Date),
        sa.Column("period_end", sa.Date),
        sa.Column("note", sa.Text),
        sa.Column("recorded_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="contract",
    )
    op.create_index("ix_sla_obs_mapping", "sla_observations", ["mapping_id"], schema="contract")
    op.create_index("ix_sla_obs_project", "sla_observations", ["project_id"], schema="contract")
    op.create_index("ix_sla_obs_activity", "sla_observations", ["activity_id"], schema="contract")
    op.create_index("ix_sla_obs_mapping_period", "sla_observations", ["mapping_id", "period_end"], schema="contract")

    op.create_table(
        "sla_evaluation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mapping_id", sa.String(36),
            sa.ForeignKey("contract.sla_activity_mappings.id", ondelete="CASCADE",
                          name="fk_sla_result_mapping"),
            nullable=False,
        ),
        sa.Column("sla_id", sa.String(36), nullable=False),
        sa.Column("sla_ref", sa.String(64)),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("milestone_id", sa.String(36)),
        sa.Column("project_id", sa.String(36)),
        sa.Column("evaluated_on", sa.Date, nullable=False),
        sa.Column("period_start", sa.Date),
        sa.Column("period_end", sa.Date),
        sa.Column("formula_type", sa.String(32)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("met", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("breached", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("severity_level", sa.Integer),
        sa.Column("accumulated_points", sa.Numeric(18, 4)),
        sa.Column("ld_percent", sa.Numeric(9, 4)),
        sa.Column("ld_amount", sa.Numeric(18, 2)),
        sa.Column("ld_base_amount", sa.Numeric(18, 2)),
        sa.Column("ld_base_kind", sa.String(32)),
        sa.Column("target_days", sa.Numeric(12, 2)),
        sa.Column("actual_days", sa.Numeric(12, 2)),
        sa.Column("delay_days", sa.Numeric(12, 2)),
        sa.Column("observed_value", postgresql.JSONB),
        sa.Column("breaches", postgresql.JSONB),
        sa.Column("notes", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("mapping_id", "evaluated_on", name="uq_sla_result_mapping_date"),
        schema="contract",
    )
    op.create_index("ix_sla_result_project_date", "sla_evaluation_results", ["project_id", "evaluated_on"], schema="contract")
    op.create_index("ix_sla_result_activity", "sla_evaluation_results", ["activity_id"], schema="contract")
    op.create_index("ix_sla_result_milestone", "sla_evaluation_results", ["milestone_id"], schema="contract")
    op.create_index("ix_sla_result_status", "sla_evaluation_results", ["status"], schema="contract")
    op.create_index("ix_sla_result_evaluated_on", "sla_evaluation_results", ["evaluated_on"], schema="contract")


def downgrade() -> None:
    op.drop_table("sla_evaluation_results", schema="contract")
    op.drop_table("sla_observations", schema="contract")
