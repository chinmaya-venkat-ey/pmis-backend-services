"""G25 + G26 — Project/activity/milestone linkage on sla_definitions + sla_templates table.

G25: Add project_id, activity_id, milestone_id (soft cross-service FKs) to sla_definitions.
     These are nullable UUIDs — soft references to project.projects, project.activities,
     project.milestones respectively. No DB-level FK constraint (cross-service boundary).

G26: New sla_templates table — reusable SLA blueprints that can be instantiated per-contract.
     Allows the same SLA pattern (e.g. "BSP Biometric Accuracy") to be reused across contracts
     and activities without re-entering all parameters each time.

Revision ID: 0003_g25_g26
Revises: 0002_phase0_gaps
Create Date: 2026-05-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_g25_g26"
down_revision = "0002_phase0_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # G25 — add project_id, activity_id, milestone_id to sla_definitions
    # Soft cross-service references — no DB FK constraint.
    # -----------------------------------------------------------------------
    op.add_column(
        "sla_definitions",
        sa.Column("project_id", sa.String(36), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("activity_id", sa.String(36), nullable=True),
        schema="contract",
    )
    op.add_column(
        "sla_definitions",
        sa.Column("milestone_id", sa.String(36), nullable=True),
        schema="contract",
    )

    op.create_index(
        "ix_sla_def_project_id",
        "sla_definitions",
        ["project_id"],
        schema="contract",
    )
    op.create_index(
        "ix_sla_def_activity_id",
        "sla_definitions",
        ["activity_id"],
        schema="contract",
    )

    # -----------------------------------------------------------------------
    # G26 — create sla_templates table
    # Reusable SLA blueprints; instantiated into sla_definitions per-contract.
    # -----------------------------------------------------------------------
    op.create_table(
        "sla_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_ref", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "formula_id",
            sa.String(36),
            sa.ForeignKey("contract.formula_library.id"),
            nullable=False,
        ),
        sa.Column("default_dsl", sa.Text, nullable=False),
        sa.Column(
            "applicable_to",
            sa.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        schema="contract",
    )

    op.create_index(
        "ix_sla_templates_formula_id",
        "sla_templates",
        ["formula_id"],
        schema="contract",
    )
    op.create_index(
        "ix_sla_templates_is_active",
        "sla_templates",
        ["is_active"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index("ix_sla_templates_is_active", table_name="sla_templates", schema="contract")
    op.drop_index("ix_sla_templates_formula_id", table_name="sla_templates", schema="contract")
    op.drop_table("sla_templates", schema="contract")

    op.drop_index("ix_sla_def_activity_id", table_name="sla_definitions", schema="contract")
    op.drop_index("ix_sla_def_project_id", table_name="sla_definitions", schema="contract")
    op.drop_column("sla_definitions", "milestone_id", schema="contract")
    op.drop_column("sla_definitions", "activity_id", schema="contract")
    op.drop_column("sla_definitions", "project_id", schema="contract")
