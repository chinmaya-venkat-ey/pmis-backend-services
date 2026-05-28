"""Cleanup: drop unused tables, add severity_level to sla_condition_bands.

Dropped (no longer needed with form-based onboarding):
  - sla_asl_snapshots   : ASL JSON snapshots (evaluation reads from normalized tables)
  - sla_dsl_versions    : DSL version history (dsl_source on sla_definitions is sufficient)
  - sla_templates       : template-based SLA creation (replaced by form-based onboarding)
  - audit_log           : never wired up in any route or service

Added:
  - sla_condition_bands.severity_level (INTEGER, nullable)
    Generic severity level (0-4) for the form-based condition builder.
    The evaluation engine maps severity_level → points via severity_master,
    then points → LD% via project_ld_config.points_ld_map.
    Nullable so existing formula-engine rows (rate_percent / points_contribution) still work.

Revision ID: 0006_cleanup
Revises: 0005_master_tables
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_cleanup"
down_revision = "0005_master_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Drop tables — dependency order matters
    #    sla_asl_snapshots.dsl_version_id → sla_dsl_versions  ← drop ASL first
    # -----------------------------------------------------------------------
    op.drop_table("sla_asl_snapshots", schema="contract")
    op.drop_table("sla_dsl_versions", schema="contract")
    op.drop_table("sla_templates", schema="contract")
    op.drop_table("audit_log", schema="contract")

    # -----------------------------------------------------------------------
    # 2. Add severity_level to sla_condition_bands
    # -----------------------------------------------------------------------
    op.add_column(
        "sla_condition_bands",
        sa.Column("severity_level", sa.Integer, nullable=True),
        schema="contract",
    )
    op.create_index(
        "ix_sla_cond_bands_severity",
        "sla_condition_bands",
        ["sla_id", "severity_level"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("ix_sla_cond_bands_severity", table_name="sla_condition_bands", schema="contract")
    op.drop_column("sla_condition_bands", "severity_level", schema="contract")

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("changed_by", sa.String(36)),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("old_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("new_data", postgresql.JSONB(astext_type=sa.Text())),
        schema="contract",
    )
    op.create_table(
        "sla_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("formula_id", sa.String(36), sa.ForeignKey("contract.formula_library.id"), nullable=False),
        sa.Column("template_ref", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("default_dsl", sa.Text, nullable=False),
        sa.Column("applicable_to", postgresql.ARRAY(sa.String(64))),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_table(
        "sla_dsl_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sla_id", sa.String(36), sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("dsl_text", sa.Text, nullable=False),
        sa.Column("change_reason", sa.Text),
        sa.Column("authored_by", sa.String(36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
    op.create_table(
        "sla_asl_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sla_id", sa.String(36), sa.ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dsl_version_id", sa.String(36), sa.ForeignKey("contract.sla_dsl_versions.id"), nullable=False),
        sa.Column("asl_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parser_version", sa.String(20), nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        schema="contract",
    )
