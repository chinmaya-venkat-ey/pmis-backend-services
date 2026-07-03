"""Create project_cf_pool_installment (frequency-based carry-forward pool).

Revision ID: p1a000000023
Revises: p1a000000022
Create Date: 2026-07-02

Backs the FREQUENCY (pool) carry-forward family: when a phase carries forward by
a time_* method the leftover is NOT applied to any phase — it becomes a schedule
of dated installments over the calendar periods after the phase ends, up to the
project end, which invoicing later draws from. One live row per (project,
source_phase, period_index).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000023"
down_revision: str = "p1a000000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_cf_pool_installment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.projects.id"), nullable=False),
        sa.Column("source_phase", sa.String(64), nullable=False),
        sa.Column("frequency_code", sa.String(16), nullable=False),
        sa.Column("period_index", sa.Integer, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("invoice_ref", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="project",
    )
    op.create_index(
        "idx_cf_pool_project_live", "project_cf_pool_installment",
        ["project_id", "deleted_at"], schema="project",
    )
    op.create_index(
        "uq_cf_pool_live", "project_cf_pool_installment",
        ["project_id", "source_phase", "period_index"],
        unique=True, schema="project",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_cf_pool_live", table_name="project_cf_pool_installment", schema="project")
    op.drop_index("idx_cf_pool_project_live", table_name="project_cf_pool_installment", schema="project")
    op.drop_table("project_cf_pool_installment", schema="project")
