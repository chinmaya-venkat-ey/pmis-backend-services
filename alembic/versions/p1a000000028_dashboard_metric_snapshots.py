"""Add dashboard_metric_snapshots table.

Revision ID: p1a000000028
Revises: p1a000000027
Create Date: 2026-07-15

Why:
  The summary dashboard shows month-over-month ``delta`` strings and
  6-month ``spark`` arrays for its KPI tiles. Those require a history of
  KPI values, which nothing persisted before. This table stores one row
  per (metric, scope, date); a shared-secret cron endpoint writes the
  current values daily and the dashboard reads the history back.

Columns:
  captured_date  the calendar date this value represents
  scope_type     'global' today; 'org'/'project' reserved for later
  scope_id       '' for global (non-null so the unique index is reliable)
  metric_key     e.g. total_projects / contract_value / delayed_projects
  value          NUMERIC(18,2) raw value (rupees for money metrics)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "p1a000000028"
down_revision: str = "p1a000000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_metric_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default=sa.text("'global'")),
        sa.Column("scope_id", sa.String(36), nullable=False, server_default=sa.text("''")),
        sa.Column("metric_key", sa.String(48), nullable=False),
        sa.Column("value", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "captured_date", "scope_type", "scope_id", "metric_key",
            name="uq_dashboard_metric_snapshot",
        ),
        schema="project",
    )
    op.create_index(
        "idx_dashboard_metric_snapshot_lookup",
        "dashboard_metric_snapshots",
        ["metric_key", "scope_type", "scope_id", "captured_date"],
        schema="project",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_dashboard_metric_snapshot_lookup",
        table_name="dashboard_metric_snapshots",
        schema="project",
    )
    op.drop_table("dashboard_metric_snapshots", schema="project")
