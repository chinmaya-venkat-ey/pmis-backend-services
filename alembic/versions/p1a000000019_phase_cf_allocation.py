"""Create project_phase_cf_allocation (custom carry-forward per-recipient shares).

Revision ID: p1a000000019
Revises: p1a000000018
Create Date: 2026-06-29

Backs the ``*_custom`` carry-forward methods: when a phase carries forward with
phase_custom / milestone_custom, its leftover is split by an explicit
per-recipient share (percent or amount, normalised to percent) instead of
evenly. One live row per (project, source_phase, recipient_key).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000019"
down_revision: str = "p1a000000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_phase_cf_allocation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("source_phase", sa.String(64), nullable=False),
        sa.Column("recipient_kind", sa.String(16), nullable=False),
        sa.Column("recipient_key", sa.String(64), nullable=False),
        sa.Column("alloc_mode", sa.String(8), nullable=False),
        sa.Column("input_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index(
        "idx_phase_cf_alloc_project_live", "project_phase_cf_allocation",
        ["project_id", "deleted_at"], schema="project",
    )
    op.create_index(
        "uq_phase_cf_alloc_live", "project_phase_cf_allocation",
        ["project_id", "source_phase", "recipient_key"],
        unique=True, schema="project",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_phase_cf_alloc_live", table_name="project_phase_cf_allocation", schema="project")
    op.drop_index("idx_phase_cf_alloc_project_live", table_name="project_phase_cf_allocation", schema="project")
    op.drop_table("project_phase_cf_allocation", schema="project")
