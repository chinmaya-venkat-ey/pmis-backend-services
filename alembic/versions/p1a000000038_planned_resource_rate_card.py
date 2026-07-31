"""Planned resources: role + per-year rate card (drop masters-designation link).

Revision ID: p1a000000038
Revises: p1a000000037
Create Date: 2026-07-30

Why:
  Planned-resource costing moves off the (now-removed) masters designation
  catalog's flat monthly_rate onto the leave-management per-contract-year rate
  cards (`/api/designation-rates`). The client supplies the designation `role`
  + its `rateCardByYear`; the BE splits the deployment window by contract year.
  So: drop `designation_id` + `monthly_rate_snapshot`; add `role`,
  `rate_card_snapshot` (the client's rateCardByYear) and `cost_by_year` (the
  per-year cost breakdown). `computed_cost` / `duration_months` are retained.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p1a000000038"
down_revision = "p1a000000037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("planned_resources", sa.Column("role", sa.String(255), nullable=True), schema="project")
    op.add_column("planned_resources", sa.Column("rate_card_snapshot", postgresql.JSONB(), nullable=True), schema="project")
    op.add_column("planned_resources", sa.Column("cost_by_year", postgresql.JSONB(), nullable=True), schema="project")
    op.drop_column("planned_resources", "designation_id", schema="project")
    op.drop_column("planned_resources", "monthly_rate_snapshot", schema="project")


def downgrade() -> None:
    op.add_column("planned_resources", sa.Column("monthly_rate_snapshot", sa.Numeric(12, 2), nullable=True), schema="project")
    # Re-added nullable (the original was NOT NULL, but rows created under the
    # rate-card model carry no designation_id to backfill).
    op.add_column("planned_resources", sa.Column("designation_id", sa.String(36), nullable=True), schema="project")
    op.drop_column("planned_resources", "cost_by_year", schema="project")
    op.drop_column("planned_resources", "rate_card_snapshot", schema="project")
    op.drop_column("planned_resources", "role", schema="project")
