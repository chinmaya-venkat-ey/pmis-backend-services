"""Recurring-cost frequency on project_cost_items.

Revision ID: p1a000000025
Revises: p1a000000024
Create Date: 2026-07-09

Adds ``project.project_cost_items.frequency_code`` — the billing frequency a
``recurring_cost`` row's amount is distributed across (monthly / quarterly /
half_yearly / yearly; logical FK to masters.frequencies.code). NULL for every
other cost type.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "p1a000000025"
down_revision: str = "p1a000000024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_cost_items",
        sa.Column("frequency_code", sa.String(length=32), nullable=True),
        schema="project",
    )


def downgrade() -> None:
    op.drop_column("project_cost_items", "frequency_code", schema="project")
