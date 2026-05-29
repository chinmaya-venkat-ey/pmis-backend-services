"""Per-project LD% bands — points_threshold → ld_percent.

The evaluator already reads contract.severity_master to resolve level→points.
This migration adds the symmetric points→LD% chart so a project can fully
override the RFP defaults baked into the evaluator.

  severity_master    : (project, level)             -> (points, label)
  project_ld_bands   : (project, points_threshold)  -> (ld_percent, label)

Rows are seeded externally (POST /api/v3/projects/{project_id}/seed-master-defaults
in master_routes) — never auto-created here, so an existing project keeps its
old hand-curated values across upgrades.

Revision ID: 0012_project_ld_bands
Revises: 0011_sla_activity_mappings
Create Date: 2026-05-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_project_ld_bands"
down_revision = "0011_sla_activity_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_ld_bands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column(
            "points_threshold",
            sa.Numeric(10, 2),
            nullable=False,
            comment="Inclusive lower-bound points value. Evaluator walks the table "
                    "ascending and uses the highest threshold the accumulated points meet.",
        ),
        sa.Column(
            "ld_percent",
            sa.Numeric(7, 3),
            nullable=False,
            comment="LD% to apply when accumulated points >= points_threshold.",
        ),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id", "points_threshold", name="uq_pldb_project_threshold",
        ),
        schema="contract",
    )
    op.create_index(
        "ix_pldb_project_id",
        "project_ld_bands",
        ["project_id"],
        schema="contract",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pldb_project_id", table_name="project_ld_bands", schema="contract",
    )
    op.drop_table("project_ld_bands", schema="contract")
